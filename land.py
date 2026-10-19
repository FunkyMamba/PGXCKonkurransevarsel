"""Landtabell: ISO3-kode -> (norsk navn, region, engelske navn/koder som brukes av CIVL og Airtribune)."""

# region: Europa, Nord-Amerika, Sør-Amerika, Asia, Oseania, Afrika
_RAW = """
ALB|Albania|Europa|albania|al
AND|Andorra|Europa|andorra|ad
ARG|Argentina|Sør-Amerika|argentina|ar
ARM|Armenia|Asia|armenia|am
AUS|Australia|Oseania|australia|au
AUT|Østerrike|Europa|austria|at
AZE|Aserbajdsjan|Asia|azerbaijan|az
BEL|Belgia|Europa|belgium|be
BGR|Bulgaria|Europa|bulgaria|bg|bul
BIH|Bosnia-Hercegovina|Europa|bosnia and herzegovina|ba
BOL|Bolivia|Sør-Amerika|bolivia|bo
BRA|Brasil|Sør-Amerika|brazil|br
CAN|Canada|Nord-Amerika|canada|ca
CHE|Sveits|Europa|switzerland|ch|sui
CHL|Chile|Sør-Amerika|chile|cl|chi
CHN|Kina|Asia|china|cn
COL|Colombia|Sør-Amerika|colombia|co
CRI|Costa Rica|Nord-Amerika|costa rica|cr|crc
CUB|Cuba|Nord-Amerika|cuba|cu
CYP|Kypros|Europa|cyprus|cy
CZE|Tsjekkia|Europa|czechia|czech republic|cz
DEU|Tyskland|Europa|germany|de|ger
DNK|Danmark|Europa|denmark|dk|den
DOM|Den dominikanske republikk|Nord-Amerika|dominican republic|do
ECU|Ecuador|Sør-Amerika|ecuador|ec
EGY|Egypt|Afrika|egypt|eg
ESP|Spania|Europa|spain|es
EST|Estland|Europa|estonia|ee
FIN|Finland|Europa|finland|fi
FRA|Frankrike|Europa|france|fr|reunion|réunion
GBR|Storbritannia|Europa|united kingdom|great britain|uk|england|scotland|wales|gb
GEO|Georgia|Asia|georgia|ge
GRC|Hellas|Europa|greece|gr|gre
GTM|Guatemala|Nord-Amerika|guatemala|gt
HKG|Hongkong|Asia|hong kong|hk
HRV|Kroatia|Europa|croatia|hr|cro
HUN|Ungarn|Europa|hungary|hu
IDN|Indonesia|Asia|indonesia|id|ina
IND|India|Asia|india|in
IRL|Irland|Europa|ireland|ie
IRN|Iran|Asia|iran|ir|iri
ISL|Island|Europa|iceland|is
ISR|Israel|Asia|israel|il
ITA|Italia|Europa|italy|it
JOR|Jordan|Asia|jordan|jo
JPN|Japan|Asia|japan|jp
KAZ|Kasakhstan|Asia|kazakhstan|kz
KEN|Kenya|Afrika|kenya|ke
KGZ|Kirgisistan|Asia|kyrgyzstan|kg
KOR|Sør-Korea|Asia|korea|south korea|korea, republic of|kr
LBN|Libanon|Asia|lebanon|lb
LIE|Liechtenstein|Europa|liechtenstein|li
LKA|Sri Lanka|Asia|sri lanka|lk
LTU|Litauen|Europa|lithuania|lt
LUX|Luxembourg|Europa|luxembourg|lu
LVA|Latvia|Europa|latvia|lv
MAR|Marokko|Afrika|morocco|ma
MDA|Moldova|Europa|moldova|md
MEX|Mexico|Nord-Amerika|mexico|mx
MKD|Nord-Makedonia|Europa|north macedonia|macedonia|mk
MLT|Malta|Europa|malta|mt
MNE|Montenegro|Europa|montenegro|me
MNG|Mongolia|Asia|mongolia|mn
MYS|Malaysia|Asia|malaysia|my|mas
NAM|Namibia|Afrika|namibia|na
NLD|Nederland|Europa|netherlands|nl|ned
NOR|Norge|Europa|norway|no
NPL|Nepal|Asia|nepal|np
NZL|New Zealand|Oseania|new zealand|nz
PAK|Pakistan|Asia|pakistan|pk
PAN|Panama|Nord-Amerika|panama|pa
PER|Peru|Sør-Amerika|peru|pe
PHL|Filippinene|Asia|philippines|ph|phi
POL|Polen|Europa|poland|pl
PRT|Portugal|Europa|portugal|pt|por
PRY|Paraguay|Sør-Amerika|paraguay|py|par
ROU|Romania|Europa|romania|ro
RUS|Russland|Europa|russia|russian federation|ru
SAU|Saudi-Arabia|Asia|saudi arabia|sa
SRB|Serbia|Europa|serbia|rs
SVK|Slovakia|Europa|slovakia|sk
SVN|Slovenia|Europa|slovenia|si|slo
SWE|Sverige|Europa|sweden|se
THA|Thailand|Asia|thailand|th
TUR|Tyrkia|Europa|turkey|türkiye|turkiye|tr
TWN|Taiwan|Asia|chinese taipei|taiwan|tw|tpe
UKR|Ukraina|Europa|ukraine|ua
URY|Uruguay|Sør-Amerika|uruguay|uy|uru
USA|USA|Nord-Amerika|united states|usa|us
UZB|Usbekistan|Asia|uzbekistan|uz
VEN|Venezuela|Sør-Amerika|venezuela|ve
VNM|Vietnam|Asia|vietnam|viet nam|vn|vie
XKX|Kosovo|Europa|kosovo|xk|kos
ZAF|Sør-Afrika|Afrika|south africa|za|rsa
"""

LAND = {}      # ISO3 -> {"navn":..., "region":...}
_OPPSLAG = {}  # alle kjente navn/koder (små bokstaver) -> ISO3

for line in _RAW.strip().splitlines():
    iso3, navn, region, *alias = line.split("|")
    LAND[iso3] = {"navn": navn, "region": region}
    for a in [iso3.lower(), *alias]:
        _OPPSLAG.setdefault(a.strip().lower(), iso3)


def finn_land(*kandidater):
    """Prøv koder og navn i rekkefølge; returner ISO3 eller ''."""
    for k in kandidater:
        if not k:
            continue
        k = k.strip().lower()
        if k in _OPPSLAG:
            return _OPPSLAG[k]
    return ""
