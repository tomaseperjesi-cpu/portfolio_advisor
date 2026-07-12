# Formát Claude export CSV

Univerzálny súbor na prenos dát zo screenshotov (cez Claude chat) do aplikácie.
Import je merge-safe: prázdne bunky sa ignorujú a neprepisujú existujúce dáta.

## Stĺpce

| Stĺpec | Povinný | Hodnoty |
|---|---|---|
| ticker | ÁNO | napr. MSFT |
| name | nie | názov firmy |
| group | nie | názov sekcie/watchlistu |
| zacks_rank | nie | 1–5, voliteľne so šípkou: 1+, 3- |
| value / growth / momentum / vgm | nie | A–F, voliteľne +/- |
| sws_fv_pct | nie | +49.3 = podhodnotené, -854.4 = nadhodnotené |
| snowflake | nie | 1–5 alebo green/lime/yellow/orange/red |
| analyst_target | nie | číslo (cieľová cena) |
| consensus | nie | Strong Buy / Buy / Hold / Sell |
| industry_rank_pct | nie | percentil odvetvia (Top 5 % → 5) |
| qty / currency / price | nie | pozícia z T212 výpisu (mena USD/EUR/GBX/GBP/CAD); hodnota v EUR sa dopočíta |
| value_eur | nie | alternatíva: priamo hodnota pozície v EUR |

## Prompt pre Claude chat

> Prečítaj priložené screenshoty (Zacks watchlist / Simply Wall St) a vytvor CSV
> súbor podľa formátu: ticker,zacks_rank,value,growth,momentum,vgm,sws_fv_pct,
> snowflake,analyst_target. Nečitateľné bunky nechaj prázdne. Snowflake zapíš
> ako farbu ikony (green/lime/yellow/orange/red).
