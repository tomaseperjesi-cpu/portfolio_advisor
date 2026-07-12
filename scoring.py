# -*- coding: utf-8 -*-
"""Metodika syntetického skóre 0-100.

Komponenty a defaultné váhy:
  - Zacks Rank        0.30  (1=100, 2=75, 3=50, 4=25, 5=0)
  - Zacks VGM         0.15  (A=100, B=75, C=50, D=25, F=0)
  - SWS valuácia      0.25  (50 + clamp(pct, -100, 100)/2; fallback = Value os z CSV)
  - SWS snowflake     0.20  (osi Future/Past/Health [+Dividend] z CSV, alebo úroveň 1-5)
  - Konsenzus         0.10  (Strong Buy=100, Buy=70, Hold=40, Sell=10)

Pri chýbajúcich vstupoch sa váhy renormalizujú (vážený priemer dostupných komponentov).
"""

DEFAULT_WEIGHTS = {
    "zacks_rank": 0.30,
    "zacks_vgm": 0.15,
    "sws_val": 0.25,
    "snowflake": 0.20,
    "consensus": 0.10,
    "industry": 0.00,   # Zacks Industry Rank - voliteľné, default vypnuté
}

DEFAULT_PARAMS = {
    "val_clamp": 100,          # orezanie SWS valuácie na +/- X %
    "flag_underval": 40,       # prah podhodnotenia pre vlajky (%)
    "flag_overval": -50,       # prah nadhodnotenia pre vlajky (%)
    "verdict_acc": 70,         # akumulovať
    "verdict_hold_plus": 55,   # držať +
    "verdict_hold": 40,        # držať
    "verdict_reduce": 25,      # zvážiť redukciu (pod tým kandidát na predaj)
    "snow_include_dividend": False,  # zahrnúť os Dividend do snowflake bodov
}

RANK_PTS = {"1": 100, "2": 75, "3": 50, "4": 25, "5": 0}
GRADE_PTS = {"A": 100, "B": 75, "C": 50, "D": 25, "F": 0}
CONS_PTS = {"Strong Buy": 100, "Buy": 70, "Hold": 40, "Sell": 10}
SNOW_LEVEL_PTS = {1: 0, 2: 25, 3: 50, 4: 75, 5: 100}

RANK_COLORS = {"1": "#1f9d23", "2": "#0f6b3f", "3": "#e0951f", "4": "#8b1a1a", "5": "#d32f2f"}
RANK_LABELS = {"1": "Strong Buy", "2": "Buy", "3": "Hold", "4": "Sell", "5": "Strong Sell"}
SNOW_COLORS = {5: "#1f9d23", 4: "#8db600", 3: "#e0c020", 2: "#e07a1f", 1: "#d32f2f"}
SNOW_LABELS = {5: "silné", 4: "dobré", 3: "priemer", 2: "slabšie", 1: "slabé"}
CONS_COLORS = {"Strong Buy": "#0f6b3f", "Buy": "#1f9d23", "Hold": "#e0951f",
               "Sell": "#8b1a1a", "bez dát": "#999999"}


def base(x):
    """Odstráni šípku zmeny (+/-) z ranku alebo grade."""
    return x.rstrip("+-") if isinstance(x, str) else x


def snowflake_level_from_axes(axes, include_dividend=False):
    """Prevedie SWS osi (0-6) na úroveň 1-5. axes = dict value/future/past/health/dividend."""
    keys = ["future", "past", "health"] + (["dividend"] if include_dividend else [])
    vals = [axes.get(k) for k in keys if axes.get(k) is not None]
    if not vals:
        return None
    pct = sum(vals) / (6 * len(vals))  # 0..1
    if pct >= 0.80: return 5
    if pct >= 0.60: return 4
    if pct >= 0.40: return 3
    if pct >= 0.20: return 2
    return 1


def valuation_points(entry, params):
    """Body za valuáciu: preferuje explicitné FV % (screenshot), fallback Value os z CSV."""
    pct = entry.get("sws_fv_pct")
    if pct is not None:
        c = params["val_clamp"]
        return max(0.0, min(100.0, 50 + max(-c, min(c, pct)) / (c / 50))), True
    axes = entry.get("sws_axes") or {}
    if axes.get("value") is not None:
        return axes["value"] / 6 * 100, False
    return None, False


def snowflake_points(entry, params):
    lvl = entry.get("snow_level")
    axes = entry.get("sws_axes")
    if axes:
        lvl = snowflake_level_from_axes(axes, params["snow_include_dividend"])
    if lvl is None:
        return None, None
    return SNOW_LEVEL_PTS[int(lvl)], int(lvl)


def compute_score(entry, weights=None, params=None):
    """Vráti dict: score, flag, verdict, incomplete, snow_level."""
    w = weights or DEFAULT_WEIGHTS
    p = params or DEFAULT_PARAMS
    parts = []

    rk = entry.get("zacks_rank")
    if rk and base(rk) in RANK_PTS:
        parts.append((RANK_PTS[base(rk)], w["zacks_rank"]))
    vgm = entry.get("zacks_vgm")
    if vgm and base(vgm) in GRADE_PTS:
        parts.append((GRADE_PTS[base(vgm)], w["zacks_vgm"]))
    val_pts, has_explicit_fv = valuation_points(entry, p)
    if val_pts is not None:
        parts.append((val_pts, w["sws_val"]))
    snow_pts, snow_level = snowflake_points(entry, p)
    if snow_pts is not None:
        parts.append((snow_pts, w["snowflake"]))
    cons = entry.get("consensus")
    if cons in CONS_PTS:
        parts.append((CONS_PTS[cons], w["consensus"]))
    ir = entry.get("industry_rank_pct")
    if ir is not None and w.get("industry", 0) > 0:
        # ir = percentil odvetvia (Top X% -> X); menšie = lepšie
        parts.append((max(0.0, min(100.0, 100 - float(ir))), w["industry"]))

    if not parts:
        return {"score": None, "flag": "", "verdict": "–", "incomplete": True, "snow_level": snow_level}

    total_w = sum(x[1] for x in parts)
    score = round(sum(a * b for a, b in parts) / total_w)

    # vlajky konfliktných signálov (len ak je rank aj explicitná FV valuácia)
    flag = ""
    pct = entry.get("sws_fv_pct")
    if pct is not None and rk and base(rk) in RANK_PTS and snow_level is not None:
        r = int(base(rk))
        if pct >= p["flag_underval"] and snow_level <= 2 and r >= 4:
            flag = "value trap?"
        elif pct <= p["flag_overval"] and r <= 2:
            flag = "drahé momentum"
        elif pct >= p["flag_underval"] and r <= 2 and snow_level >= 3:
            flag = "dvojitý signál +"
        elif pct <= p["flag_overval"] and r >= 4:
            flag = "dvojitý signál −"

    if flag == "value trap?":
        verdict = "⚠ value trap?"
    elif score >= p["verdict_acc"]:
        verdict = "akumulovať"
    elif score >= p["verdict_hold_plus"]:
        verdict = "držať +"
    elif score >= p["verdict_hold"]:
        verdict = "držať"
    elif score >= p["verdict_reduce"]:
        verdict = "zvážiť redukciu"
    else:
        verdikt = "kandidát na predaj"
        verdict = verdikt

    incomplete = (rk is None) or (val_pts is None and snow_pts is None)
    return {"score": score, "flag": flag, "verdict": verdict,
            "incomplete": incomplete, "snow_level": snow_level}


VERDICT_COLORS = {
    "akumulovať": "#0f6b3f",
    "držať +": "#1f9d23",
    "držať": "#e0951f",
    "zvážiť redukciu": "#e07a1f",
    "kandidát na predaj": "#d32f2f",
    "⚠ value trap?": "#d32f2f",
    "–": "#aaaaaa",
}

METHODOLOGY_MD = """
### Ako sa počíta syntetické skóre (0–100)

Skóre kombinuje päť nezávislých signálov s rôznymi časovými horizontmi:

| Komponent | Default váha | Čo meria | Prevod na body |
|---|---|---|---|
| **Zacks Rank** | 30 % | revízie odhadov ziskov (1–3 mes.) | 1→100, 2→75, 3→50, 4→25, 5→0 |
| **Zacks VGM** | 15 % | style kompozit Value/Growth/Momentum | A→100 … F→0 |
| **SWS valuácia** | 25 % | % pod/nad DCF fair value | 50 + clamp(%, ±100)/2; fallback os Value z CSV (0–6 → 0–100) |
| **SWS snowflake** | 20 % | kvalita fundamentov | osi Future+Past+Health z CSV → úroveň 1–5 → 0/25/50/75/100 |
| **Konsenzus** | 10 % | rating analytikov | Strong Buy→100, Buy→70, Hold→40, Sell→10 |
| **Industry Rank** | 0 % (voliteľné) | Zacks poradie odvetvia | body = 100 − percentil (Top 5 % → 95 b.) |

Ak niektorý vstup chýba, jeho váha sa **renormalizuje** – skóre je vážený priemer len
z dostupných komponentov. Neúplné skóre (chýba Zacks alebo celý SWS blok) je označené `*`.

**Vlajky konfliktných signálov** (vyžadujú rank + explicitnú FV valuáciu zo screenshotu):

- `dvojitý signál +` – podhodnotené ≥ prah A zároveň Zacks 1–2 a snowflake ≥ 3 → najlepší setup
- `drahé momentum` – Zacks 1–2, ale nadhodnotené ≤ prah → cyklické riziko
- `value trap?` – podhodnotené, ale snowflake ≤ 2 a Zacks 4–5 → prepisuje verdikt
- `dvojitý signál −` – nadhodnotené a Zacks 4–5 → najhorší setup

**Verdikty:** ≥ 70 akumulovať · 55–69 držať + · 40–54 držať · 25–39 zvážiť redukciu · < 25 kandidát na predaj.

Skóre je orientačná syntéza verejných ratingov, **nie investičné odporúčanie**. SWS fair
value je modelový odhad, konsenzus analytikov má systematický optimistický bias.
"""
