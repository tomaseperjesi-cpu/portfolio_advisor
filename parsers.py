# -*- coding: utf-8 -*-
"""Parsery vstupov: Trading 212 PDF, Simply Wall St CSV, screenshoty (Zacks / SWS) cez Claude API."""
import base64
import io
import json
import re

import pandas as pd
import pdfplumber

CURRENCIES = ("USD", "EUR", "GBX", "GBP", "CAD", "CHF", "SEK", "DKK", "NOK", "JPY", "PLN", "CZK")

# riadok tabuľky: Názov ISIN Množstvo MENA Cena
ROW_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s+(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<cur>" + "|".join(CURRENCIES) + r")\s+(?P<price>\d+(?:[\.,]\d+)?)\s*$"
)


def parse_t212_pdf(file_bytes):
    """Parsuje Trading 212 'Confirmation of holdings' PDF.

    Vracia (rows, total_value_str) kde rows = list dictov
    {name, isin, qty, currency, price}.
    """
    rows, total = [], None
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                m = ROW_RE.match(line)
                if m:
                    rows.append({
                        "name": m.group("name").strip(),
                        "isin": m.group("isin"),
                        "qty": float(m.group("qty")),
                        "currency": m.group("cur"),
                        "price": float(m.group("price").replace(",", ".")),
                    })
                elif "Holdings value:" in line and total is None:
                    tm = re.search(r"Holdings value:\s*([\d,\.]+)\s*(\w+)", line)
                    if tm:
                        total = f"{tm.group(1)} {tm.group(2)}"
    return rows, total


def _num(x):
    """SWS CSV obsahuje záporné čísla ako \"'-0.66\" – očistí a prevedie na float."""
    if pd.isna(x) or x == "":
        return None
    s = str(x).replace("'", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_sws_csv(file_bytes):
    """Parsuje Simply Wall St portfolio/watchlist CSV export.

    Vracia list dictov: symbol, name, sws_axes{value,future,past,health,dividend},
    market_value, shares, avg_price, total_return_pct.
    """
    df = pd.read_csv(io.BytesIO(file_bytes))
    out = []
    for _, r in df.iterrows():
        sym = str(r.get("Symbol", "")).strip().upper()
        if not sym or sym == "NAN":
            continue
        out.append({
            "symbol": sym,
            "name": str(r.get("Company", "")).strip(),
            "sws_axes": {
                "value": _num(r.get("Value Score")),
                "future": _num(r.get("Future Score")),
                "past": _num(r.get("Past Score")),
                "health": _num(r.get("Health Score")),
                "dividend": _num(r.get("Dividend Score")),
            },
            "market_value": _num(r.get("Market Value")),
            "shares": _num(r.get("Shares")),
            "avg_price": _num(r.get("Average Price")),
            "total_return_pct": _num(r.get("Total Return %")),
        })
    return out


# ---------------------------------------------------------------- Zacks online

def fetch_zacks_online(symbols, timeout=10, pause=0.4):
    """Stiahne Zacks Rank z verejného quote feedu (https://quote-feed.zacks.com).

    Neoficiálny endpoint (rovnaký princíp ako repo zacks-api) - môže sa kedykoľvek
    zmeniť. Vracia (rows, errors); rows = {ticker, zacks_rank, name, updated}.
    Style scores (VGM) feed neobsahuje.
    """
    import time
    import requests
    rows, errors = [], []
    headers = {"User-Agent": "Mozilla/5.0 (portfolio-synteza; personal use)"}
    for sym in symbols:
        s = str(sym).strip().upper()
        if not s:
            continue
        try:
            r = requests.get(f"https://quote-feed.zacks.com/index?t={s}",
                             headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json().get(s) or {}
            rank = str(data.get("zacks_rank") or "").strip()
            if rank in {"1", "2", "3", "4", "5"}:
                rows.append({"ticker": s, "zacks_rank": rank,
                             "name": data.get("name", ""),
                             "updated": data.get("updated", ""),
                             "last_price": data.get("last"),
                             "pct_change": data.get("percent_net_change"),
                             "dividend_yield": data.get("dividend_yield"),
                             "pe_f1": data.get("pe_f1"),
                             "earnings_date": (data.get("confirmed_reporting_date")
                                               or None)})
            else:
                errors.append(f"{s}: feed nevrátil rank (neznámy ticker alebo zmena feedu)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s}: {e}")
        time.sleep(pause)
    return rows, errors


# ---------------------------------------------------------------- screenshoty

ZACKS_PROMPT = """Na obrázku je tabuľka zo Zacks.com (watchlist/portfolio tracker).
Pre KAŽDÝ riadok vytiahni: ticker, zacks_rank (číslo 1-5 vo farebnom štvorčeku; ak má
šípku hore pridaj '+', dole '-'), a štyri písmenové grady v poradí stĺpcov:
value, growth, momentum, vgm (A-F, šípky opäť ako +/-; VGM je čierny štvorček úplne vpravo).
Nečitateľné bunky vráť ako "?". Riadky s NA vráť s hodnotami "NA".
Vráť ČISTÝ JSON array bez akéhokoľvek ďalšieho textu:
[{"ticker":"MSFT","zacks_rank":"3","value":"C","growth":"B","momentum":"A","vgm":"B"}]"""

SWS_PROMPT = """Na obrázku je zoznam akcií zo Simply Wall St.
Pre KAŽDÝ riadok vytiahni:
- ticker
- fv_pct: číslo z textu "X% undervalued" ako kladné, "X% overvalued" ako záporné (napr. -854.4)
- snowflake_color: farba ikony snowflake, jedna z: "green","lime","yellow","orange","red"
- analyst_target: číselná hodnota Analyst Target ak je viditeľná, inak null
Vráť ČISTÝ JSON array bez akéhokoľvek ďalšieho textu:
[{"ticker":"VST","fv_pct":70.1,"snowflake_color":"orange","analyst_target":222.89}]"""

SNOW_COLOR_TO_LEVEL = {"green": 5, "lime": 4, "yellow": 3, "orange": 2, "red": 1}


def extract_from_screenshots(images, kind, api_key, model="claude-sonnet-4-6"):
    """Vytiahne dáta zo screenshotov cez Claude API (vision).

    images: list (filename, bytes, mime); kind: 'zacks' | 'sws'.
    Vracia (rows, errors).
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    prompt = ZACKS_PROMPT if kind == "zacks" else SWS_PROMPT
    rows, errors = [], []
    for fname, data, mime in images:
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=4000,
                messages=[{"role": "user", "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": mime,
                                "data": base64.b64encode(data).decode()}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            parsed = json.loads(text)
            for r in parsed:
                r["_source"] = fname
            rows.extend(parsed)
        except Exception as e:  # noqa: BLE001 - chyby zobrazujeme používateľovi
            errors.append(f"{fname}: {e}")
    return rows, errors


STYLE_RE = re.compile(
    r"Value:\s*</span>\s*<span[^>]*>\s*([A-F])|"
    r"class=\"composite_val[^\"]*\"[^>]*>\s*([A-F])", re.I)


def fetch_zacks_style_scores(symbols, timeout=10, pause=0.6):
    """EXPERIMENTÁLNE: skúsi vytiahnuť style scores a industry rank
    z verejnej quote stránky zacks.com/stock/quote/TICKER.

    Stránka má bot ochranu a markup sa mení - pri zlyhaní vráti chybu
    pre daný ticker a dáta ostávajú na screenshotovom vstupe.
    Vracia (rows, errors); rows = {ticker, value, growth, momentum, vgm,
    industry_rank_pct}.
    """
    import time
    import requests
    rows, errors = [], []
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for sym in symbols:
        s2 = str(sym).strip().upper()
        if not s2:
            continue
        try:
            r = requests.get(f"https://www.zacks.com/stock/quote/{s2}",
                             headers=headers, timeout=timeout)
            r.raise_for_status()
            html = r.text
            # style scores: blok "Style Scores" obsahuje 4 hodnoty v poradí V/G/M/VGM
            m = re.search(
                r"Style Scores.*?([A-F])\s*Value.*?([A-F])\s*Growth"
                r".*?([A-F])\s*Momentum.*?([A-F])\s*VGM",
                html, re.S | re.I)
            ir = re.search(r"Industry Rank.*?(Top|Bottom)\s*(\d+)%", html, re.S | re.I)
            if m:
                rows.append({
                    "ticker": s2,
                    "value": m.group(1).upper(), "growth": m.group(2).upper(),
                    "momentum": m.group(3).upper(), "vgm": m.group(4).upper(),
                    "industry_rank_pct": (int(ir.group(2)) if ir and ir.group(1).lower() == "top"
                                          else 100 - int(ir.group(2)) if ir else None),
                })
            else:
                errors.append(f"{s2}: style scores sa na stránke nenašli (zmena markupu / bot ochrana)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s2}: {e}")
        time.sleep(pause)
    return rows, errors


# ---------------------------------------------------------------- SWS online (experimentálne)

def fetch_sws_online(symbols, timeout=12, pause=0.6):
    """EXPERIMENTÁLNE: snowflake osi z interného SWS grid API.

    Postup pre každý ticker: (1) search endpoint nájde firmu a jej id,
    (2) grid/filter (include=info,score) vráti score.data = value/income/health/past/future.
    Interné, nedokumentované API - môže sa kedykoľvek zmeniť alebo vyžadovať auth.
    Vracia (rows, errors); rows = {ticker, name, unique_symbol, sws_axes}.
    """
    import time
    import requests
    rows, errors = [], []
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://simplywall.st",
        "Referer": "https://simplywall.st/",
    }
    for sym in symbols:
        t = str(sym).strip().upper()
        if not t:
            continue
        try:
            sr = requests.get("https://api.simplywall.st/api/search/companies",
                              params={"query": t}, headers=headers, timeout=timeout)
            sr.raise_for_status()
            hits = sr.json() or []
            hit = None
            for h in hits:
                usym = str(h.get("unique_symbol") or h.get("uniqueSymbol") or "")
                if usym.split(":")[-1].upper() == t:
                    hit = h
                    break
            hit = hit or (hits[0] if hits else None)
            if not hit or not hit.get("id"):
                errors.append(f"{t}: search nenašiel firmu")
                time.sleep(pause)
                continue
            cid = hit["id"]
            payload = {"id": "1", "no_result_if_limit": True, "offset": 0,
                       "size": 1, "state": "read",
                       "rules": json.dumps([["id", "in", [cid]],
                                            ["primary_flag", "=", True]])}
            gr = requests.post(
                "https://api.simplywall.st/api/grid/filter?include=info,score",
                json=payload, headers=headers, timeout=timeout)
            gr.raise_for_status()
            items = (gr.json().get("data") or [])
            if not items:
                errors.append(f"{t}: grid API nevrátilo dáta (id filter nemusí byť podporovaný)")
                time.sleep(pause)
                continue
            it = items[0]
            sc = ((it.get("score") or {}).get("data")) or {}
            if not sc:
                errors.append(f"{t}: chýba score blok v odpovedi")
            else:
                rows.append({
                    "ticker": t,
                    "name": it.get("name", hit.get("name", "")),
                    "unique_symbol": it.get("unique_symbol", ""),
                    "sws_axes": {
                        "value": sc.get("value"),
                        "future": sc.get("future"),
                        "past": sc.get("past"),
                        "health": sc.get("health"),
                        "dividend": sc.get("income"),
                    },
                })
        except Exception as e:  # noqa: BLE001
            errors.append(f"{t}: {e}")
        time.sleep(pause)
    return rows, errors
