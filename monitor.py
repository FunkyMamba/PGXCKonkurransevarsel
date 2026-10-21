#!/usr/bin/env python3
"""
Konkurransevarsel – samler paragliding XC-konkurranser fra CIVL og Airtribune,
sender push-varsel via ntfy (https://ntfy.sh) når en ny dukker opp,
og lager nettsiden docs/index.html med alle konkurransene.

Kjøres automatisk av GitHub Actions (se .github/workflows/sjekk.yml),
men kan også kjøres lokalt:  python monitor.py
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from land import LAND, finn_land

# --------------------------------------------------------------------------
# INNSTILLINGER – endre her hvis det blir for mange varsler
# --------------------------------------------------------------------------

# Konkurranser med disse ordene i navnet ignoreres (små bokstaver).
EKSKLUDER_ORD = ["acro", "hang gliding", "hanggliding", "speed flying", "accuracy"]

# Bare varsle for disse regionene. Tom liste = hele verden.
# Mulige verdier: "Europa", "Nord-Amerika", "Sør-Amerika", "Asia", "Oseania", "Afrika"
KUN_REGIONER = []

# Bare varsle for disse kategoriene. Tom liste = alle.
# Mulige verdier: "Cat 1", "Cat 2", "Ikke sanksjonert"
KUN_KATEGORIER = []

# Hvis flere enn dette kommer samtidig, samles de i ett varsel.
MAKS_ENKELTVARSLER = 5

CIVL_MAKS_SIDER = 15

# --------------------------------------------------------------------------

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "sett.json"
TEMPLATE_FILE = ROOT / "side.html"
PAGE_FILE = ROOT / "docs" / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (konkurransevarsel; personlig oversikt over konkurranser)",
    "Accept-Language": "en",
}

CIVL_URL = "https://civlcomps.org/events"
CIVL_PARAMS = {
    "search[mode]": "list",
    "search[pg]": "paragliding-xc",
    "search[dates]": "upcoming",
}
AIRTRIBUNE_URL = "https://airtribune.com/events/next"

MND = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def fetch(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------
# CIVL – svarer med JSON når forespørselen er merket som AJAX
# --------------------------------------------------------------------------

def _civl_dato(s):
    try:
        return datetime.strptime(s, "%Y/%m/%d").date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_civl_json(data):
    events = []
    for e in data.get("events", []):
        m = re.search(r"/event/([^/?#]+)", e.get("eventLink") or "")
        if not m:
            continue
        kat = e.get("faiCategory")
        kategori = f"Cat {kat}" if str(kat) in ("1", "2") else "Ikke sanksjonert"
        try:
            deltakere = int(e.get("participantsCount"))
        except (TypeError, ValueError):
            deltakere = None
        try:
            lat, lon = float(e.get("latitude")), float(e.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
        events.append({
            "id": "civl:" + m.group(1),
            "kilde": "CIVL",
            "navn": clean(e.get("eventTitle") or m.group(1)),
            "start": _civl_dato(e.get("start")),
            "slutt": _civl_dato(e.get("end")),
            "sted": clean(e.get("cityTitle")).strip(" ,"),
            "land": finn_land(e.get("countryIso3"), e.get("countryTitle")),
            "kategori": kategori,
            "deltakere": deltakere,
            "lat": lat, "lon": lon,
            "url": f"https://civlcomps.org/event/{m.group(1)}",
        })
    return events


def get_civl():
    alle = {}
    for side in range(CIVL_MAKS_SIDER):
        params = {**CIVL_PARAMS, "search[page]": str(side)}
        r = requests.get(CIVL_URL, params=params, timeout=30,
                         headers={**HEADERS, "X-Requested-With": "XMLHttpRequest",
                                  "Accept": "application/json, text/javascript, */*"})
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            print(f"CIVL svarte ikke med JSON: {r.text[:200]!r}", file=sys.stderr)
            break
        found = parse_civl_json(data)
        for e in found:
            alle[e["id"]] = e
        if side + 1 >= int(data.get("pagesCount") or 1) or not found:
            break
    return list(alle.values())


# --------------------------------------------------------------------------
# AIRTRIBUNE – listen gir navn og "X days left"; hver konkurranseside har
# dato og sted i <meta name="description">, f.eks. "07 - 14 Nov, 2026 | Tapalpa, Mexico"
# --------------------------------------------------------------------------

AT_IKKE_EVENTS = {"events", "welcome", "docs", "static", "competition-hosting-and-live-tracking",
                  "leagues", "users", "pilots", "api", "media", "news", "about"}

AT_DATO_RE = re.compile(
    r"(\d{1,2})(?:\s+([A-Za-z]{3})[a-z]*)?(?:,?\s*(\d{4}))?\s*[–-]\s*"
    r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*,?\s*(\d{4})")


def parse_at_beskrivelse(desc):
    """'07 - 14 Nov, 2026 | Tapalpa, Mexico' -> (start, slutt, sted, landnavn)"""
    start = slutt = sted = landnavn = ""
    deler = [clean(d) for d in (desc or "").split("|")]
    m = AT_DATO_RE.search(deler[0] if deler else "")
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        try:
            mm2 = MND[m2.lower()]
            mm1 = MND[m1.lower()] if m1 else mm2
            yy2 = int(y2)
            yy1 = int(y1) if y1 else (yy2 - 1 if mm1 > mm2 else yy2)
            start = date(yy1, mm1, int(d1)).isoformat()
            slutt = date(yy2, mm2, int(d2)).isoformat()
        except (KeyError, ValueError):
            pass
    if len(deler) > 1:
        steder = [clean(x) for x in deler[1].split(",") if clean(x)]
        if steder:
            landnavn = steder[-1]
            sted = ", ".join(steder[:-1])
    return start, slutt, sted, landnavn


def parse_airtribune(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    scope = soup
    heading = soup.find(lambda t: t.name in ("h1", "h2", "h3") and "upcoming" in t.get_text().lower())
    if heading is not None:
        scope = heading.parent or soup
    events = {}
    for a in scope.find_all("a", href=True):
        u = urlparse(urljoin("https://airtribune.com/", a["href"]))
        if u.netloc and "airtribune.com" not in u.netloc:
            continue
        parts = [p for p in u.path.split("/") if p]
        if len(parts) != 1 or parts[0] in AT_IKKE_EVENTS:
            continue
        slug = parts[0]
        klasser = " ".join(a.get("class") or [])
        if "hang" in klasser:  # hanggliding
            continue
        tittel = a.select_one(".title")
        navn = clean(tittel.get_text(" ") if tittel else a.get_text(" "))
        tid = a.select_one(".time-info")
        tidtekst = clean(tid.get_text(" ")) if tid else ""
        if not tid:
            m = re.search(r"(\d+)\s+days?\s+left.*$", navn, re.I)
            if m:
                tidtekst, navn = m.group(0), clean(navn[: m.start()])
        flagg = a.select_one("[class*=countryflag-]")
        iso2 = ""
        if flagg:
            m = re.search(r"countryflag-([a-z]{2})", " ".join(flagg.get("class") or []))
            iso2 = m.group(1) if m else ""
        if not navn:
            continue
        start = ""
        m = re.search(r"(\d+)\s+days?\s+left", tidtekst, re.I)
        if m:
            start = (date.today() + timedelta(days=int(m.group(1)))).isoformat()
        events[slug] = {
            "id": "airtribune:" + slug,
            "kilde": "Airtribune",
            "navn": navn,
            "start": start, "slutt": "",
            "sted": "",
            "land": finn_land(iso2),
            "kategori": "",
            "deltakere": None,
            "lat": None, "lon": None,
            "url": f"https://airtribune.com/{slug}/",
        }
    return list(events.values())


def airtribune_detaljer(ev, kjent):
    """Henter dato og sted fra konkurransesiden (bare første gang vi ser den)."""
    if kjent and kjent.get("slutt") and kjent.get("sted") is not None and kjent.get("_detaljer"):
        for k in ("start", "slutt", "sted", "land"):
            ev[k] = kjent.get(k) or ev[k]
        ev["_detaljer"] = True
        return ev
    try:
        soup = BeautifulSoup(fetch(ev["url"]), "html.parser")
        meta = soup.find("meta", attrs={"name": "description"}) or \
            soup.find("meta", attrs={"property": "og:description"})
        start, slutt, sted, landnavn = parse_at_beskrivelse(meta.get("content") if meta else "")
        ev["start"] = start or ev["start"]
        ev["slutt"] = slutt
        ev["sted"] = sted
        ev["land"] = finn_land(landnavn) or ev["land"]
        ev["_detaljer"] = True
    except Exception as exc:
        print(f"Airtribune-detaljer feilet for {ev['url']}: {exc}", file=sys.stderr)
    return ev


def parse_airtribune_data(page_html: str):
    """Airtribune legger hele listen i sidekoden: window.ATDATA.eventLists = {...};
    'next-events' har alle kommende konkurranser, 'current-events' de som pågår."""
    m = re.search(r"window\.ATDATA\.eventLists\s*=\s*(\{.*?\});\s*\n", page_html, re.S)
    if not m:
        return None
    try:
        lists = json.loads(m.group(1))
    except ValueError:
        return None
    events = {}
    for key in ("current-events", "next-events"):
        for e in (lists.get(key) or {}).get("content") or []:
            if e.get("sport") not in (0, None):          # 0 = paragliding
                continue
            url = e.get("url") or ""
            if e.get("status") == -1 and e.get("googleplus_url"):
                url = e["googleplus_url"]                  # ekstern konkurranseside
            slug = url.strip("/").split("/")[-1] if url.startswith("/") else str(e.get("id"))
            start, slutt = e.get("start_date") or "", e.get("end_date") or ""
            try:  # medlemskap o.l. som varer et helt år er ikke konkurranser
                if (date.fromisoformat(slutt) - date.fromisoformat(start)).days > 45:
                    continue
            except ValueError:
                pass
            land = (e.get("country") or {})
            steder = [clean(x) for x in (e.get("place") or "").split(",") if clean(x)]
            sted = ", ".join(steder[:-1]) if len(steder) > 1 else ""
            events[slug] = {
                "id": "airtribune:" + slug,
                "kilde": "Airtribune",
                "navn": clean(e.get("title")),
                "start": start, "slutt": slutt,
                "sted": sted,
                "land": finn_land(land.get("code"), land.get("ioc_code"), land.get("name"),
                                  steder[-1] if steder else ""),
                "kategori": "",   # Airtribune sin kategori-kode samsvarer ikke sikkert med FAI/CIVL
                "deltakere": None,
                "lat": e.get("lat"), "lon": e.get("lon"),
                "url": urljoin("https://airtribune.com/", url),
                "_detaljer": True,
            }
    return list(events.values())


def get_airtribune(state=None):
    page = fetch(AIRTRIBUNE_URL)
    events = parse_airtribune_data(page)
    if events:
        return events
    # Reserve: les de synlige kortene og hent detaljer fra hver konkurranseside
    print("Airtribune: fant ikke datalisten i siden, bruker reserve", file=sys.stderr)
    sett = (state or {}).get("sett", {})
    return [airtribune_detaljer(e, sett.get(e["id"])) for e in parse_airtribune(page)]


# --------------------------------------------------------------------------
# Kobling av samme konkurranse på begge sidene
# --------------------------------------------------------------------------

STOPPORD = {"open", "paragliding", "parapente", "pg", "championship", "championships", "cup", "copa",
            "the", "and", "del", "las", "los", "fai", "league", "liga", "nacional", "national",
            "xc", "edition", "edicion", "event", "test", "pre", "pwc", "prepwc", "world",
            "category", "cat", "open"}


def _ord(tekst):
    return {w for w in re.findall(r"[a-zà-ÿ]{3,}", (tekst or "").lower()) if w not in STOPPORD}


def samme(a, b):
    if not a.get("start") or a.get("start") != b.get("start"):
        return False
    # Doble oppføringer på samme side må også ha samme sluttdato
    if a["kilde"] == b["kilde"]:
        if not a.get("slutt") or a.get("slutt") != b.get("slutt") or a.get("land") != b.get("land"):
            return False
        # ... og navnene må ligne (samme sted alene er ikke nok)
        return len(_ord(a["navn"]) & _ord(b["navn"])) >= 1
    if a.get("land") and b.get("land") and a["land"] != b["land"]:
        return False
    return bool(_ord(a["navn"] + " " + a.get("sted", "")) & _ord(b["navn"] + " " + b.get("sted", "")))


def slå_sammen(events):
    """Grupperer like konkurranser. CIVL-data foretrekkes (kategori, kart)."""
    grupper = []
    for ev in sorted(events, key=lambda e: e["kilde"] != "CIVL"):
        for g in grupper:
            if any(samme(ev, x) for x in g):
                g.append(ev)
                break
        else:
            grupper.append([ev])
    return grupper


# --------------------------------------------------------------------------
# Filtrering, varsling, lagring, nettside
# --------------------------------------------------------------------------

def region(ev):
    return LAND.get(ev.get("land"), {}).get("region", "")


def er_xc(ev) -> bool:
    navn = ev["navn"].lower() + " "
    return not any(o in navn for o in EKSKLUDER_ORD)


def skal_varsles(ev) -> bool:
    if not er_xc(ev):
        return False
    if KUN_REGIONER and region(ev) not in KUN_REGIONER:
        return False
    if KUN_KATEGORIER and ev.get("kategori") and ev["kategori"] not in KUN_KATEGORIER:
        return False
    return True


# --------------------------------------------------------------------------
# Påmelding – antall påmeldte og maks plasser.
# CIVL: påmeldte følger med i listen; maks plasser står på konkurransesiden
#       (<span class="count">120</span><span>max allowed</span>), hentes ukentlig.
# Airtribune: konkurransesiden har window.ATDATA.pilots med "totalRegistered" og
#       "allowed2" (maks plasser). Vi leser bare disse to tallene, ikke pilotlisten.
#       Hentes hver kjøring mens ingen er påmeldt, ellers én gang i døgnet.
# Påmeldingen regnes som åpnet når antall påmeldte går fra 0 til 1 eller flere.
# --------------------------------------------------------------------------

PAUSE_MELLOM_OPPSLAG = 1.0  # sekunder, for å være snill mot sidene


def _alder_timer(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 1e9


def civl_maks(url):
    html = fetch(url)
    maks = re.search(r'class="count">\s*(\d+)\s*</span>\s*<span>\s*max allowed', html, re.I)
    pam = re.search(r'class="count">\s*(\d+)\s*</span>\s*<span>\s*pilots registered', html, re.I)
    return (int(maks.group(1)) if maks else None), (int(pam.group(1)) if pam else None)


def airtribune_pamelding(url):
    html = fetch(url.rstrip("/") + "/info")
    blokk = re.search(r"window\.ATDATA\.pilots\s*=\s*", html)
    if not blokk:
        return None, None
    rest = html[blokk.end(): blokk.end() + 2_000_000]
    tot = re.search(r'"totalRegistered"\s*:\s*(\d+)', rest)
    maks = re.search(r'"allowed2"\s*:\s*(\d+)', rest)
    return (int(tot.group(1)) if tot else None), (int(maks.group(1)) if maks else None)


def oppdater_pamelding(current, tidligere_reg, now):
    """Fyller ev["reg"] = {pameldt, maks, ...} og returnerer konkurransene som nettopp åpnet."""
    i_dag = date.today().isoformat()
    apnet = []
    oppslag = 0
    for ev in current:
        reg = dict(tidligere_reg.get(ev["id"]) or {})
        forrige = reg.get("pameldt")
        if not ev.get("start") or ev["start"] < i_dag or not er_xc(ev):
            ev["reg"] = reg
            continue
        try:
            if ev["kilde"] == "CIVL":
                reg["pameldt"] = ev.get("deltakere") or 0
                if reg.get("maks") is None or _alder_timer(reg.get("maks_hentet")) > 24 * 7:
                    time.sleep(PAUSE_MELLOM_OPPSLAG)
                    maks, pam = civl_maks(ev["url"])
                    oppslag += 1
                    reg["maks"] = maks
                    reg["maks_hentet"] = now
                    if pam is not None and not ev.get("deltakere"):
                        reg["pameldt"] = pam
            elif ev["kilde"] == "Airtribune" and "airtribune.com" in ev["url"]:
                if forrige in (None, 0) or _alder_timer(reg.get("hentet")) > 20:
                    time.sleep(PAUSE_MELLOM_OPPSLAG)
                    pam, maks = airtribune_pamelding(ev["url"])
                    oppslag += 1
                    if pam is not None:
                        reg["pameldt"] = pam
                    if maks:
                        reg["maks"] = maks
                    reg["hentet"] = now
        except Exception as exc:
            print(f"Påmeldingstall feilet for {ev['url']}: {exc}", file=sys.stderr)
        if forrige == 0 and (reg.get("pameldt") or 0) > 0:
            reg["apnet"] = now
            apnet.append(ev)
        ev["reg"] = reg
    print(f"Påmelding: {oppslag} konkurransesider sjekket, {len(apnet)} har åpnet")
    return apnet


def gruppe_reg(g):
    """Velger påmeldingstallene fra kilden med flest påmeldte."""
    regs = [x.get("reg") or {} for x in g]
    beste = max(regs, key=lambda r: (r.get("pameldt") or 0, r.get("maks") or 0), default={})
    return {
        "pameldt": beste.get("pameldt"),
        "maks": beste.get("maks") or next((r["maks"] for r in regs if r.get("maks")), None),
        "apnet": max((r["apnet"] for r in regs if r.get("apnet")), default=""),
    }


def notify(title, message, url=None, priority="default", tags="parachute"):
    if not NTFY_TOPIC:
        print(f"[ingen NTFY_TOPIC] {title}: {message}")
        return
    headers = {"Title": title.encode("utf-8"), "Priority": priority, "Tags": tags}
    if url:
        headers["Click"] = url
    try:
        requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers=headers, timeout=20)
    except Exception as exc:
        print(f"Varsel feilet: {exc}", file=sys.stderr)


def beskriv(ev):
    def kort(iso):
        try:
            d = date.fromisoformat(iso)
            return f"{d.day}. {['jan','feb','mar','apr','mai','jun','jul','aug','sep','okt','nov','des'][d.month-1]} {d.year}"
        except (TypeError, ValueError):
            return ""
    dato = kort(ev.get("start"))
    if ev.get("slutt") and ev.get("slutt") != ev.get("start"):
        dato = f"{dato} – {kort(ev['slutt'])}"
    landnavn = LAND.get(ev.get("land"), {}).get("navn", ev.get("land", ""))
    sted = ", ".join(x for x in (ev.get("sted"), landnavn) if x)
    return " · ".join(x for x in (dato, sted, ev.get("kategori"), ev["kilde"]) if x)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"sett": {}, "feil": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")


def lag_data(grupper, sett, startet=""):
    i_dag = date.today().isoformat()
    ut = []
    for g in grupper:
        h = g[0]  # CIVL først hvis den finnes
        ut.append({
            "navn": h["navn"],
            "start": next((x["start"] for x in g if x.get("start")), ""),
            "slutt": next((x["slutt"] for x in g if x.get("slutt")), ""),
            "sted": next((x["sted"] for x in g if x.get("sted")), ""),
            "land": h.get("land") or next((x["land"] for x in g if x.get("land")), ""),
            "landnavn": LAND.get(h.get("land"), {}).get("navn", h.get("land", "")),
            "region": region(h),
            "kategori": next((x["kategori"] for x in g if x.get("kategori") in ("Cat 1", "Cat 2")),
                             next((x["kategori"] for x in g if x.get("kategori")), "")),
            **{k: v for k, v in gruppe_reg(g).items()},
            "lat": h.get("lat"), "lon": h.get("lon"),
            "funnet": min(sett.get(x["id"], {}).get("funnet", i_dag) for x in g),
            "kilder": list({x["kilde"]: {"kilde": x["kilde"], "url": x["url"]} for x in reversed(g)}.values())[::-1],
        })
    ut = [e for e in ut if not e["slutt"] or e["slutt"] >= i_dag]
    ut.sort(key=lambda e: e["start"] or "9999")
    return {"oppdatert": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "startet": startet, "konkurranser": ut}


def skriv_side(data):
    PAGE_FILE.parent.mkdir(exist_ok=True)
    json_tekst = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if TEMPLATE_FILE.exists():
        html = TEMPLATE_FILE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json_tekst)
    else:
        html = f"<!doctype html><meta charset=utf-8><pre>{json_tekst}</pre>"
    PAGE_FILE.write_text(html, encoding="utf-8")
    (PAGE_FILE.parent / "konkurranser.json").write_text(json_tekst, encoding="utf-8")


def main():
    state = load_state()
    state.setdefault("feil", {})
    first_run = not state["sett"]
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")

    current = []
    for kilde, fn in (("CIVL", get_civl), ("Airtribune", lambda: get_airtribune(state))):
        try:
            found = fn()
        except Exception as exc:
            print(f"Feil ved {kilde}: {exc}", file=sys.stderr)
            found = None
        if not found:
            n = state["feil"].get(kilde, 0) + 1
            state["feil"][kilde] = n
            if n == 3:
                notify(f"⚠️ {kilde} gir ingen treff",
                       f"Konkurransevarselet har ikke funnet noe på {kilde} tre ganger på rad. "
                       "Nettsiden kan ha endret seg – skriptet må kanskje justeres.",
                       priority="high", tags="warning")
            # Behold det vi sist så fra denne kilden, så nettsiden ikke tømmes
            current.extend(v for v in state["sett"].values()
                           if v.get("kilde") == kilde and v.get("start", "9999") >= date.today().isoformat())
            continue
        state["feil"][kilde] = 0
        print(f"{kilde}: {len(found)} konkurranser")
        current.extend(found)

    kjente_kilder = {v["kilde"] for v in state["sett"].values()}
    nye_kilder = {e["kilde"] for e in current} - kjente_kilder
    # Versjon 2 leser hele Airtribune-listen (ikke bare de 6 første). Første kjøring
    # med den lagrer de "nye" stille, siden de bare var usynlige før.
    if state.get("versjon", 1) < 2 and not first_run and "Airtribune" in {e["kilde"] for e in current}:
        nye_kilder.add("Airtribune")
    state["versjon"] = 2
    gamle_ids = set(state["sett"])
    tidligere_reg = {k: v.get("reg") for k, v in state["sett"].items() if v.get("reg")}

    for ev in current:
        tidligere = state["sett"].get(ev["id"], {})
        ev["funnet"] = tidligere.get("funnet", now)
        state["sett"][ev["id"]] = ev

    apnet_ids = {e["id"] for e in oppdater_pamelding(current, tidligere_reg, now)}

    grupper = slå_sammen([e for e in current if er_xc(e)])

    # En konkurranse er ny bare hvis ingen i gruppen er sett før
    # (samme konkurranse som dukker opp på den andre siden gir ikke nytt varsel)
    new = []
    for g in grupper:
        if any(x["id"] in gamle_ids for x in g):
            continue
        if any(x["kilde"] in nye_kilder for x in g):
            continue
        h = g[0]
        if skal_varsles(h):
            new.append(h)

    if first_run:
        notify("Konkurransevarsel er i gang ✅",
               f"Fant {len(grupper)} kommende konkurranser. Du får varsel når nye dukker opp.")
    elif nye_kilder:
        antall = sum(1 for e in current if e["kilde"] in nye_kilder)
        notify(f"{' og '.join(sorted(nye_kilder))} oppdatert ✅",
               f"Leser nå {antall} kommende konkurranser derfra. Du får varsel når nye dukker opp.")

    if not first_run:
        if len(new) > MAKS_ENKELTVARSLER:
            liste = "\n".join(f"• {e['navn']} ({beskriv(e)})" for e in new[:20])
            notify(f"{len(new)} nye konkurranser", liste)
        else:
            gruppe_av = {x["id"]: g for g in grupper for x in g}
            for e in new:
                r = gruppe_reg(gruppe_av.get(e["id"], [e]))
                tekst = beskriv(e)
                if (r.get("pameldt") or 0) > 0:
                    tekst = (f"Påmelding åpen: {r['pameldt']} påmeldt"
                             + (f" av {r['maks']}" if r.get("maks") else "") + " · " + tekst)
                notify(f"Ny: {e['navn']}", tekst, url=e["url"])

    print(f"Nye relevante: {len(new)}")

    # Påmelding åpnet – vurderes for konkurransen samlet, på tvers av kildene.
    # Åpnet = konkurransen var kjent med 0 påmeldte (i alle kjente kilder), og nå
    # har minst én kilde påmeldte. Dekker også at påmeldingen ligger på en annen
    # side enn der konkurransen først dukket opp (f.eks. CIVL-konkurranse med
    # påmelding på Airtribune), selv om den siden allerede har påmeldte når vi ser den.
    apnet = []
    for g in grupper:
        kjente = [tidligere_reg.get(x["id"]) for x in g if x["id"] in gamle_ids]
        kjente = [r for r in kjente if r and r.get("pameldt") is not None]
        if not kjente:
            continue  # aldri sett påmeldingstall for denne før
        if any((r.get("pameldt") or 0) > 0 or r.get("apnet") for r in kjente):
            continue  # var allerede åpen
        if any(x["id"] in apnet_ids for x in g) or (gruppe_reg(g).get("pameldt") or 0) > 0:
            for x in g:
                if (x.get("reg") or {}).get("pameldt"):
                    x["reg"]["apnet"] = now
            h = g[0]
            if skal_varsles(h):
                kilde = max(g, key=lambda x: (x.get("reg") or {}).get("pameldt") or 0)
                apnet.append((h, gruppe_reg(g), kilde["url"]))
    if not first_run:
        if len(apnet) > MAKS_ENKELTVARSLER:
            liste = "\n".join(f"• {h['navn']} ({beskriv(h)})" for h, r, u in apnet[:20])
            notify(f"Påmelding åpnet for {len(apnet)} konkurranser 📝", liste, tags="memo")
        else:
            for h, r, u in apnet:
                plasser = f"{r['pameldt']} påmeldt" + (f" av {r['maks']} plasser" if r.get("maks") else "")
                notify(f"Påmelding åpnet: {h['navn']} 📝", f"{plasser} · {beskriv(h)}",
                       url=u, priority="high", tags="memo")
    print(f"Påmelding åpnet: {len(apnet)}")

    # Rydd bort gamle konkurranser fra lagringen (over et år etter slutt)
    grense = (date.today() - timedelta(days=365)).isoformat()
    state["sett"] = {k: v for k, v in state["sett"].items()
                     if (v.get("slutt") or v.get("start") or "9999") >= grense or not v.get("start")}
    save_state(state)
    if not state.get("startet"):
        state["startet"] = min((v.get("funnet") for v in state["sett"].values() if v.get("funnet")), default=now)
    save_state(state)
    skriv_side(lag_data(grupper, state["sett"], state["startet"]))


if __name__ == "__main__":
    main()
