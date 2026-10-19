#!/usr/bin/env python3
"""
Konkurransevarsel – overvåker CIVL og Airtribune for nye paragliding XC-konkurranser
og sender push-varsel via ntfy (https://ntfy.sh) når en ny dukker opp.

Kjøres automatisk av GitHub Actions (se .github/workflows/sjekk.yml),
men kan også kjøres lokalt:  python monitor.py
"""

import json
import os
import re
import sys
import html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# INNSTILLINGER – endre her hvis det blir for mange varsler
# --------------------------------------------------------------------------

# Konkurranser med disse ordene i navnet ignoreres (små bokstaver).
# Airtribune har f.eks. også acro- og hanggliderkonkurranser.
EKSKLUDER_ORD = ["acro", "hang gliding", "hanggliding", "hg ", "speed flying", "accuracy"]

# Sett til f.eks. ["norway", "spain", "slovenia"] for kun å få varsel når
# landet/stedet står i teksten. Tom liste = alle land.
KUN_DISSE_ORDENE = []

# Hvis flere enn dette kommer samtidig, samles de i ett varsel.
MAKS_ENKELTVARSLER = 5

# Hvor mange CIVL-sider som maksimalt leses (sikring mot evig løkke).
CIVL_MAKS_SIDER = 15

# --------------------------------------------------------------------------

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "sett.json"
PAGE_FILE = ROOT / "docs" / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (konkurransevarsel; personlig overvaking av konkurranser)",
    "Accept-Language": "en",
}

CIVL_URL = "https://civlcomps.org/events"
CIVL_PARAMS = {
    "search[mode]": "list",
    "search[pg]": "paragliding-xc",
    "search[dates]": "upcoming",
}
AIRTRIBUNE_URL = "https://airtribune.com/events/next"

MND = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    r"(\d{1,2}\s*" + MND + r"\s*\d{0,4}\s*[–\-]\s*\d{1,2}\s*" + MND + r"\s*\d{0,4}"
    r"|\d{1,2}\s*(?:[–\-]\s*\d{1,2}\s*)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{0,4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}\s*(?:[–\-]\s*\d{1,2})?,?\s*\d{0,4}"
    r"|\d{4}-\d{2}-\d{2}(?:\s*[–\-]\s*\d{4}-\d{2}-\d{2})?"
    r"|\d{1,2}\.\d{1,2}\.\d{2,4})",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------
# CIVL
# --------------------------------------------------------------------------

def parse_civl(page_html: str, base: str = "https://civlcomps.org/"):
    """Finner alle lenker til enkeltkonkurranser (/event/...) og henter navn,
    dato og sted fra lenketeksten og elementet rundt."""
    soup = BeautifulSoup(page_html, "html.parser")
    events = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        path = urlparse(href).path.rstrip("/")
        # Enkeltkonkurranser ligger på /event/<navn> (ikke /events, ikke undersider)
        m = re.fullmatch(r"/event/([^/]+)", path)
        if not m:
            continue
        url = f"https://civlcomps.org/event/{m.group(1)}"
        name = clean(a.get("title") or a.get_text(" "))
        # Finn en "rad"/"kort" rundt lenken for å hente dato og sted
        container = a
        for _ in range(5):
            if container.parent is None:
                break
            container = container.parent
            if len(clean(container.get_text(" "))) > len(name) + 15:
                break
        context = clean(container.get_text(" "))
        has_text = len(name) >= 4
        if not has_text:
            name = m.group(1).replace("-", " ").title()
        ev = events.get(url)
        # Foretrekk lenker med ekte tekst (ikke bildelenker) og den lengste konteksten
        if ev is None or (has_text and not ev["_tekst"]) or len(context) > len(ev["info"]):
            date = DATE_RE.search(context)
            events[url] = {
                "id": "civl:" + m.group(1),
                "kilde": "CIVL",
                "navn": name if (has_text or ev is None) else ev["navn"],
                "dato": clean(date.group(0)) if date else "",
                "info": context[:200],
                "url": url,
                "_tekst": has_text or (ev is not None and ev["_tekst"]),
            }
    for ev in events.values():
        ev.pop("_tekst", None)
    return list(events.values())


def get_civl():
    alle = {}
    for side in range(CIVL_MAKS_SIDER):
        params = dict(CIVL_PARAMS)
        params["search[page]"] = str(side)
        found = parse_civl(fetch(CIVL_URL, params))
        nye = [e for e in found if e["id"] not in alle]
        for e in found:
            alle[e["id"]] = e
        if not nye:  # ingen nye på denne siden -> slutt på listen
            break
    return list(alle.values())


# --------------------------------------------------------------------------
# AIRTRIBUNE
# --------------------------------------------------------------------------

AT_IKKE_EVENTS = {
    "events", "welcome", "docs", "static", "competition-hosting-and-live-tracking",
    "leagues", "users", "pilots", "api", "media", "news", "about",
}


def parse_airtribune(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    # Begrens til området under overskriften "Upcoming events" hvis den finnes
    scope = soup
    heading = soup.find(lambda t: t.name in ("h1", "h2", "h3") and "upcoming" in t.get_text().lower())
    if heading is not None:
        scope = heading.parent or soup
    events = {}
    for a in scope.find_all("a", href=True):
        href = urljoin("https://airtribune.com/", a["href"])
        u = urlparse(href)
        if u.netloc and "airtribune.com" not in u.netloc:
            continue
        parts = [p for p in u.path.split("/") if p]
        if len(parts) != 1 or parts[0] in AT_IKKE_EVENTS:
            continue
        slug = parts[0]
        text = clean(a.get_text(" "))
        if not text:
            continue
        m = re.search(r"(\d+)\s+days?\s+left|today|tomorrow|started|in progress", text, re.I)
        name = clean(text[: m.start()]) if m else text
        status = clean(m.group(0)) if m else ""
        events[slug] = {
            "id": "airtribune:" + slug,
            "kilde": "Airtribune",
            "navn": name,
            "dato": status,
            "info": text,
            "url": f"https://airtribune.com/{slug}/",
        }
    return list(events.values())


def get_airtribune():
    return parse_airtribune(fetch(AIRTRIBUNE_URL))


# --------------------------------------------------------------------------
# Filtrering, varsling, lagring
# --------------------------------------------------------------------------

def relevant(ev) -> bool:
    tekst = (ev["navn"] + " " + ev.get("info", "")).lower()
    if any(o in (ev["navn"].lower() + " ") for o in EKSKLUDER_ORD):
        return False
    if KUN_DISSE_ORDENE and not any(o.lower() in tekst for o in KUN_DISSE_ORDENE):
        return False
    return True


def notify(title, message, url=None, priority="default", tags="parachute"):
    if not NTFY_TOPIC:
        print(f"[ingen NTFY_TOPIC] {title}: {message}")
        return
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
        "Tags": tags,
    }
    if url:
        headers["Click"] = url
    requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode("utf-8"),
                  headers=headers, timeout=20)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"sett": {}, "feil": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")


def write_page(events):
    PAGE_FILE.parent.mkdir(exist_ok=True)
    rows = []
    for e in sorted(events, key=lambda e: e.get("funnet", ""), reverse=True):
        rows.append(
            f"<tr><td>{html.escape(e.get('funnet','')[:10])}</td>"
            f"<td><a href=\"{html.escape(e['url'])}\">{html.escape(e['navn'])}</a></td>"
            f"<td>{html.escape(e.get('dato',''))}</td><td>{html.escape(e['kilde'])}</td></tr>"
        )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    PAGE_FILE.write_text(f"""<!doctype html>
<html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PG XC-konkurranser</title>
<style>
:root{{--bg:#f7f8fa;--fg:#1d2330;--mut:#667;--line:#dde1e8;--acc:#1f6feb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12151b;--fg:#e6e9ef;--mut:#99a;--line:#2a2f3a;--acc:#58a6ff}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:var(--mut);margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}} td,th{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;color:var(--mut)}} a{{color:var(--acc);text-decoration:none}}
td:first-child,td:last-child{{white-space:nowrap;color:var(--mut);font-size:13px}}
</style></head><body>
<h1>Kommende PG XC-konkurranser</h1>
<p>CIVL + Airtribune · sist sjekket {now} · nyeste først</p>
<table><tr><th>Funnet</th><th>Konkurranse</th><th>Dato</th><th>Kilde</th></tr>
{''.join(rows)}
</table></body></html>""", encoding="utf-8")


def main():
    state = load_state()
    first_run = not state["sett"]
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")

    current = []
    for kilde, fn in (("CIVL", get_civl), ("Airtribune", get_airtribune)):
        try:
            found = fn()
        except Exception as exc:  # nettverksfeil e.l.
            print(f"Feil ved {kilde}: {exc}", file=sys.stderr)
            found = None
        if not found:
            # Varsle én gang hvis en kilde slutter å gi resultater (siden kan ha endret seg)
            n = state["feil"].get(kilde, 0) + 1
            state["feil"][kilde] = n
            if n == 3:
                notify(f"⚠️ {kilde} gir ingen treff",
                       f"Konkurransevarselet har ikke funnet noe på {kilde} tre ganger på rad. "
                       "Nettsiden kan ha endret seg – skriptet må kanskje justeres.",
                       priority="high", tags="warning")
            continue
        state["feil"][kilde] = 0
        print(f"{kilde}: {len(found)} konkurranser")
        current.extend(found)

    new = []
    for ev in current:
        if ev["id"] in state["sett"]:
            state["sett"][ev["id"]].update({k: ev[k] for k in ("navn", "dato", "url")})
            continue
        ev["funnet"] = now
        state["sett"][ev["id"]] = ev
        if relevant(ev):
            new.append(ev)

    if first_run:
        notify("Konkurransevarsel er i gang ✅",
               f"Fant {len(current)} kommende konkurranser. Du får varsel når nye dukker opp.")
    elif len(new) > MAKS_ENKELTVARSLER:
        liste = "\n".join(f"• {e['navn']} ({e['kilde']})" for e in new[:20])
        notify(f"{len(new)} nye konkurranser", liste, url=None)
    else:
        for e in new:
            msg = " · ".join(x for x in (e.get("dato"), e["kilde"]) if x)
            notify(f"Ny: {e['navn']}", msg or e["url"], url=e["url"])

    print(f"Nye relevante: {len(new)}")
    save_state(state)
    current_ids = {e["id"] for e in current}
    write_page([e for i, e in state["sett"].items() if i in current_ids])


if __name__ == "__main__":
    main()
