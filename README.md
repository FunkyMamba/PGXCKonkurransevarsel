# Konkurransevarsel – PG XC

Sjekker **CIVL** (paragliding XC, kommende) og **Airtribune** (neste konkurranser) hver tredje time,
og sender push-varsel til mobilen når en ny konkurranse dukker opp. Gratis, og PC-en din trenger ikke stå på.

## Oppsett (ca. 15 minutter)

### 1. Installer ntfy på mobilen
- Last ned appen **ntfy** (App Store / Google Play).
- Trykk **+** og abonner på et emne med et hemmelig navn som ingen andre gjetter,
  f.eks. `pgxc-jonna-8k3f2q`. Navnet fungerer som et passord, så ikke bruk noe enkelt.

### 2. Lag en GitHub-konto og et repo
- Gå til github.com og lag en gratis konto hvis du ikke har en.
- Trykk **New repository**, kall det f.eks. `konkurransevarsel`, velg **Private**, og trykk **Create**.

### 3. Last opp filene
- I det nye repoet: trykk **uploading an existing file**.
- Pakk ut zip-filen og dra inn **alt innholdet**, også mappen `.github`.
  (Mappen er skjult på Mac. Trykk Cmd+Shift+. i Finder for å se den.)
- Trykk **Commit changes**.

### 4. Legg inn ntfy-emnet som hemmelighet
- **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`
- Secret: emnenavnet fra steg 1 (f.eks. `pgxc-jonna-8k3f2q`)

### 5. Start første kjøring
- Gå til fanen **Actions**, velg **Sjekk nye konkurranser**, og trykk **Run workflow**.
- Etter et minutt skal du få varselet *«Konkurransevarsel er i gang ✅»*.
  Første kjøring lagrer bare alt som finnes, så du ikke får 50 varsler på en gang.
- Etter dette går den av seg selv hver tredje time.

### 6. Nettsiden PG XC-kalender
Skriptet lager `docs/index.html` med alle kommende konkurranser fra begge kildene, med søk,
filtre (region, kategori, kilde) og stjernemerking. Malen for siden er `side.html`, og landnavnene ligger i `land.py`.
- GitHub Pages er gratis for **offentlige** repoer. For et privat repo krever det et betalt abonnement.
  Repoet inneholder ingen hemmeligheter (ntfy-emnet ligger som secret), så det er trygt å gjøre det offentlig:
  **Settings → General → Danger Zone → Change visibility → Public**.
- **Settings → Pages → Source: Deploy from a branch → Branch: main, mappe /docs → Save**.
- Etter et par minutter vises adressen øverst på Pages-siden, f.eks. `https://brukernavn.github.io/PGXCKonkurransevarsel/`.
  Legg den til på hjemskjermen på mobilen, så fungerer den som en app.

## For mange varsler? Juster øverst i `monitor.py`
- `EKSKLUDER_ORD` – ord i navnet som gjør at konkurransen ignoreres (acro m.m. er med fra før).
- `KUN_DISSE_ORDENE` – f.eks. `["spain", "slovenia", "italy"]` for bare bestemte land.
- `MAKS_ENKELTVARSLER` – flere enn dette samtidig blir samlet i ett varsel.
- Hyppighet: endre `cron`-linjen i `.github/workflows/sjekk.yml` (`17 */6 * * *` = hver 6. time).

Du kan redigere filene direkte på github.com (blyant-ikonet).

## Hvis noe slutter å virke
Finner skriptet ingenting på en av sidene tre ganger på rad, får du et ⚠️-varsel.
Det betyr som regel at nettsiden har endret utseende og at skriptet må justeres.
Se loggen under **Actions** for detaljer.
