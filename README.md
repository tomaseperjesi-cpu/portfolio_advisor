# Portfólio syntéza (Zacks + Simply Wall St + konsenzus)

Streamlit aplikácia, ktorá kombinuje Trading 212 holdings, Zacks ratingy a Simply Wall St
dáta do syntetického skóre 0–100 s farebnou tabuľkou v štýle Zacks.

## Nasadenie (GitHub → Streamlit Cloud)

1. Vytvor GitHub repozitár a nahraj doň tieto súbory (`app.py`, `scoring.py`, `parsers.py`,
   `requirements.txt`).
2. Na https://share.streamlit.io vyber repozitár, main file = `app.py`.
3. Pre čítanie screenshotov pridaj v Streamlit Cloud → App settings → **Secrets**:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

   Bez kľúča funguje všetko okrem vyťažovania screenshotov (PDF aj CSV import fungujú vždy).

## Vstupy

| Zdroj | Formát | Čo z neho appka berie |
|---|---|---|
| Trading 212 | Confirmation of holdings PDF | názov, ISIN, množstvo, mena, cena → hodnota v EUR |
| Simply Wall St | CSV export portfólia/watchlistu | snowflake osi Value/Future/Past/Health/Dividend |
| Simply Wall St | screenshoty | % pod/nad fair value, farba snowflake, analyst target |
| Simply Wall St | **online (grid API)** | snowflake osi automaticky (experimentálne, interné API) |
| Zacks | **online (quote-feed)** | Zacks Rank automaticky pre všetky tickery jedným klikom |
| Zacks | screenshoty watchlistu | Zacks Rank + Value/Growth/Momentum/VGM grady |
| ručne | tabuľka v appke | konsenzus analytikov, korekcie |

Screenshoty číta Claude API (vision) a vracia štruktúrovaný JSON; výsledok si vždy
skontroluj v sekcii **Úprava dát**.

**Zacks online** používa neoficiálny verejný feed `quote-feed.zacks.com` (rovnaký princíp
ako open-source projekt zacks-api). Môže sa kedykoľvek zmeniť alebo prestať fungovať;
style scores (VGM) neobsahuje – tie sa dopĺňajú zo screenshotov. Test funkčnosti:
`curl "https://quote-feed.zacks.com/index?t=MSFT"`.

## Pamäť a sledovanie zmien

Aplikácia si dáta pamätá v `data/store.json` – pri štarte sa automaticky načítajú
a každá zmena (import, úprava, nastavenia) sa hneď ukladá. Na Streamlit Cloud tento
súbor prežije bežné rerun-y, ale zmaže sa pri reštarte kontajnera/redeployi – preto
je v záložke **Import dát → Záloha (JSON)** export/obnova celého stavu vrátane snapshotov.

**Snapshoty hodnotenia:** aplikácia si ukladá skóre všetkých akcií (automaticky pri
prvom otvorení dňa + manuálne tlačidlom 📌 v bočnom paneli, max 30 snapshotov).
V Prehľade sa zobrazuje stĺpec **Δ** so zmenou skóre voči zvolenému snapshotu,
zmenené akcie sú označené modrou bodkou a podfarbením riadku, nové akcie majú Δ „nová".
Checkbox umožňuje zobraziť len akcie so zmenou hodnotenia.

## Metodika skóre

Popísaná priamo v aplikácii (Nastavenia a metodika), váhy komponentov, prahy vlajok,
verdiktov aj FX kurzy sú meniteľné v UI. Defaulty: Zacks Rank 30 %, VGM 15 %,
SWS valuácia 25 %, snowflake 20 %, konsenzus 10 %.

Skóre je orientačná syntéza verejných ratingov, nie investičné odporúčanie.
