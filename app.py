# -*- coding: utf-8 -*-
"""Portfólio syntéza – Streamlit aplikácia.

Kombinuje Trading 212 holdings, Zacks ratingy a Simply Wall St dáta
do syntetického skóre 0-100 s farebnou tabuľkou v štýle Zacks.
Pamäť: data/store.json (automatické načítanie/ukladanie) + snapshoty hodnotenia
na sledovanie zmien skóre medzi použitiami.
"""
import datetime as dt
import difflib
import json
import pathlib
import traceback

APP_VERSION = "1.2 (diag)"

import pandas as pd
import streamlit as st

import parsers
import scoring
from scoring import (CONS_COLORS, DEFAULT_PARAMS, DEFAULT_WEIGHTS, GRADE_PTS,
                     RANK_COLORS, RANK_LABELS, SNOW_COLORS, SNOW_LABELS,
                     VERDICT_COLORS, base, compute_score)

st.set_page_config(page_title="Portfólio syntéza", page_icon="🧮", layout="wide")

STORE = pathlib.Path("data/store.json")

# ---------------------------------------------------------------- store & snapshoty

def load_store():
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_store():
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps({
        "stocks": st.session_state.stocks,
        "weights": st.session_state.weights,
        "params": st.session_state.params,
        "fx": st.session_state.fx,
        "snapshots": st.session_state.snapshots,
        "auto_snapshot": st.session_state.auto_snapshot,
    }, ensure_ascii=False), encoding="utf-8")


def current_scores():
    out = {}
    for sym, e in st.session_state.stocks.items():
        r = compute_score(e, st.session_state.weights, st.session_state.params)
        if r["score"] is not None:
            out[sym] = {"score": r["score"], "verdict": r["verdict"]}
    return out


def take_snapshot(label=""):
    st.session_state.snapshots.append({
        "ts": dt.datetime.now().isoformat(timespec="minutes"),
        "label": label,
        "scores": current_scores(),
    })
    st.session_state.snapshots = st.session_state.snapshots[-30:]  # drž max 30
    save_store()


def last_snapshot():
    return st.session_state.snapshots[-1] if st.session_state.snapshots else None


def init_state():
    if "stocks" in st.session_state:
        return
    d = load_store()
    st.session_state.stocks = d.get("stocks", {})
    st.session_state.weights = d.get("weights", dict(DEFAULT_WEIGHTS))
    st.session_state.params = {**DEFAULT_PARAMS, **d.get("params", {})}
    st.session_state.fx = d.get("fx", {"EURUSD": 1.1446, "EURGBP": 0.8559, "EURCAD": 1.622})
    st.session_state.snapshots = d.get("snapshots", [])
    st.session_state.auto_snapshot = d.get("auto_snapshot", True)
    # auto-snapshot: pri prvom spustení dňa zachyť stav z minula PRED novými zmenami
    if st.session_state.auto_snapshot and st.session_state.stocks:
        snap = last_snapshot()
        today = dt.date.today().isoformat()
        if snap is None or snap["ts"][:10] < today:
            take_snapshot("auto pri otvorení")

init_state()

CSS = """
<style>
.rk{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;
    color:#fff;font-weight:bold;border-radius:4px;font-size:13px}
.gv{display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;
    background:#dcdcdc;color:#222;font-weight:bold;border-radius:3px;font-size:12px}
.gv.vgm{background:#111;color:#fff}
.up{color:#1f9d23;font-size:9px;margin-left:2px}
.dn{color:#d32f2f;font-size:9px;margin-left:2px}
.na{color:#aaa}
.sn{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:middle}
.snl{font-size:11px;color:#666}
.fl{font-size:11px;color:#888;font-weight:normal}
.chg{display:inline-block;width:7px;height:7px;border-radius:50%;background:#2a78d6;
     margin-right:5px;vertical-align:middle}
.dpos{color:#1f9d23;font-weight:bold}
.dneg{color:#d32f2f;font-weight:bold}
.dnew{color:#2a78d6;font-size:11px;font-weight:bold}
table.zx{border-collapse:collapse;width:100%;font-size:13px;font-family:Arial,Helvetica,sans-serif}
table.zx th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
    color:#666;border-bottom:2px solid #ccc;padding:8px 6px}
table.zx td{border-bottom:1px solid #ececec;padding:7px 6px;vertical-align:middle}
table.zx tr:hover td{background:#f7f7f5}
table.zx tr.changed td{background:#f2f7ff}
table.zx tr.changed:hover td{background:#e8f1fd}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.nm{font-weight:bold;white-space:nowrap}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------- helpery

def get_entry(symbol):
    return st.session_state.stocks.setdefault(symbol.upper(), {
        "symbol": symbol.upper(), "name": "", "groups": [],
        "value_eur": None, "qty": None, "currency": None, "price": None,
        "zacks_rank": None, "zacks_v": None, "zacks_g": None, "zacks_m": None,
        "zacks_vgm": None, "sws_fv_pct": None, "snow_level": None,
        "sws_axes": None, "analyst_target": None, "consensus": None, "note": "",
    })


def value_in_eur(qty, currency, price, fx):
    if None in (qty, currency, price):
        return None
    c = str(currency).upper()
    if c == "EUR":
        return qty * price
    if c == "USD":
        return qty * price / fx["EURUSD"]
    if c == "GBX":
        return qty * price / 100 / fx["EURGBP"]
    if c == "GBP":
        return qty * price / fx["EURGBP"]
    if c == "CAD":
        return qty * price / fx["EURCAD"]
    return None


def suggest_symbol(name, known):
    names = {v["name"].lower(): k for k, v in known.items() if v.get("name")}
    match = difflib.get_close_matches(name.lower(), list(names.keys()), n=1, cutoff=0.75)
    return names[match[0]] if match else ""


def badge_rank(r):
    if not r or base(r) not in RANK_COLORS:
        return '<span class="na">–</span>'
    arrow = ('<span class="up">&#9650;</span>' if r.endswith("+")
             else '<span class="dn">&#9660;</span>' if r.endswith("-") else "")
    b = base(r)
    return f'<span class="rk" style="background:{RANK_COLORS[b]}" title="{RANK_LABELS[b]}">{b}</span>{arrow}'


def badge_grade(g, vgm=False):
    if not g or base(g) not in GRADE_PTS:
        return '<span class="na">?</span>' if g == "?" else '<span class="na">–</span>'
    arrow = ('<span class="up">&#9650;</span>' if g.endswith("+")
             else '<span class="dn">&#9660;</span>' if g.endswith("-") else "")
    cls = "gv vgm" if vgm else "gv"
    return f'<span class="{cls}">{base(g)}</span>{arrow}'


def badge_cons(c):
    if not c:
        return '<span class="na">–</span>'
    col = CONS_COLORS.get(c, "#999")
    return f'<span style="color:{col};font-weight:bold;font-size:12px">{c}</span>'


def cell_sws(entry, res):
    pct = entry.get("sws_fv_pct")
    axes = entry.get("sws_axes")
    if pct is None and not axes:
        return '<td class="na">–</td><td class="na">–</td>'
    if pct is not None:
        col, sign = ("#1f9d23", "+") if pct >= 0 else ("#d32f2f", "−")
        v = f'<span style="color:{col};font-weight:bold">{sign}{abs(pct):.0f} %</span>'
    else:
        vs = axes.get("value")
        v = (f'<span class="snl">Value os {vs:.0f}/6</span>' if vs is not None
             else '<span class="na">–</span>')
    lvl = res["snow_level"]
    sn = (f'<span class="sn" style="background:{SNOW_COLORS[lvl]}"></span> '
          f'<span class="snl">{SNOW_LABELS[lvl]}</span>') if lvl else '<span class="na">–</span>'
    return f'<td class="num">{v}</td><td>{sn}</td>'


def delta_cell(sym, score, prev_scores):
    """Δ voči poslednému snapshotu. Vracia (html_bunky, zmenené_bool)."""
    if score is None:
        return '<td class="na">–</td>', False
    if prev_scores is None:
        return '<td class="na">–</td>', False
    prev = prev_scores.get(sym)
    if prev is None:
        return '<td class="dnew">nová</td>', True
    d = score - prev["score"]
    if d == 0:
        return '<td class="num na">0</td>', False
    cls = "dpos" if d > 0 else "dneg"
    arrow = "▲" if d > 0 else "▼"
    return f'<td class="num"><span class="{cls}">{arrow} {d:+d}</span></td>', True


def fmt_eur(v):
    return f"{v:,.0f}".replace(",", " ") if v is not None else "–"


def render_table(entries, total_value, prev_scores, show_value=True):
    head_val = "<th>Hodnota €</th><th>Váha</th>" if show_value else ""
    rows_html = []
    for i, e in enumerate(entries, 1):
        res = compute_score(e, st.session_state.weights, st.session_state.params)
        sc = res["score"]
        star = "*" if (sc is not None and res["incomplete"]) else ""
        scc = f'<td class="num"><b>{sc}</b>{star}</td>' if sc is not None else '<td class="na">–</td>'
        dcell, changed = delta_cell(e["symbol"], sc, prev_scores)
        vcol = VERDICT_COLORS.get(res["verdict"], "#aaa")
        extra = (f' <span class="fl">({res["flag"]})</span>'
                 if res["flag"] and res["verdict"] != "⚠ value trap?" else "")
        verd = f'<span style="color:{vcol};font-weight:bold">{res["verdict"]}</span>{extra}'
        val_cells = ""
        if show_value:
            w = (f'{100 * e["value_eur"] / total_value:.2f} %'
                 if e.get("value_eur") and total_value else "–")
            val_cells = f'<td class="num">{fmt_eur(e.get("value_eur"))}</td><td class="num">{w}</td>'
        mark = '<span class="chg" title="zmena oproti minulému hodnoteniu"></span>' if changed else ""
        rows_html.append(
            f'<tr class="{"changed" if changed else ""}"><td class="num">{i}</td>'
            f'<td class="nm">{mark}{e["symbol"]} · {e.get("name") or ""}</td>{val_cells}'
            f'<td>{badge_cons(e.get("consensus"))}</td>'
            f'<td>{badge_rank(e.get("zacks_rank"))}</td>'
            f'<td>{badge_grade(e.get("zacks_vgm"), vgm=True)}</td>'
            f'{cell_sws(e, res)}{scc}{dcell}<td>{verd}</td></tr>')
    st.markdown(
        f'<table class="zx"><thead><tr><th>#</th><th>Ticker · Firma</th>{head_val}'
        f'<th>Konsenzus</th><th>Zacks</th><th>VGM</th><th>SWS valuácia</th>'
        f'<th>Snowflake</th><th>Skóre</th><th>Δ</th><th>Verdikt</th></tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody></table>',
        unsafe_allow_html=True)


def sort_entries(entries, mode):
    if mode == "Podľa hodnoty":
        return sorted(entries, key=lambda e: -(e.get("value_eur") or 0))
    if mode == "Podľa skóre":
        def key(e):
            s = compute_score(e, st.session_state.weights, st.session_state.params)["score"]
            return (-(s if s is not None else -1), -(e.get("value_eur") or 0))
        return sorted(entries, key=key)
    return sorted(entries, key=lambda e: e["symbol"])

# ---------------------------------------------------------------- stránky

page = st.sidebar.radio("Navigácia",
                        ["📊 Prehľad", "📥 Import dát", "✏️ Úprava dát",
                         "⚙️ Nastavenia a metodika"])
st.sidebar.markdown("---")
st.sidebar.caption(f"Načítaných akcií: **{len(st.session_state.stocks)}**")
st.sidebar.caption(f"Verzia appky: **{APP_VERSION}**")
with st.sidebar.expander("🔧 Diagnostika"):
    import sys
    checks = {
        "parsers.map_isins_openfigi": hasattr(parsers, "map_isins_openfigi"),
        "parsers.fetch_zacks_online": hasattr(parsers, "fetch_zacks_online"),
        "parsers.parse_claude_csv": hasattr(parsers, "parse_claude_csv"),
        "parsers.fetch_sws_online": hasattr(parsers, "fetch_sws_online"),
    }
    for k, ok in checks.items():
        st.caption(("✅ " if ok else "❌ CHÝBA: ") + k)
    st.caption(f"Python {sys.version.split()[0]}")
    st.caption(f"parsers.py: {pathlib.Path(parsers.__file__).stat().st_size} B")
snap = last_snapshot()
if snap:
    st.sidebar.caption(f"Posledný snapshot: **{snap['ts'].replace('T', ' ')}**"
                       + (f" ({snap['label']})" if snap.get("label") else ""))
else:
    st.sidebar.caption("Zatiaľ žiadny snapshot.")
if st.sidebar.button("📌 Uložiť snapshot hodnotenia"):
    take_snapshot("manuálny")
    st.sidebar.success("Snapshot uložený – Δ sa odteraz počíta voči nemu.")

# =============================================================== PREHĽAD
if page == "📊 Prehľad":
    st.title("Portfólio syntéza")
    stocks = list(st.session_state.stocks.values())
    if not stocks:
        st.info("Zatiaľ nie sú načítané žiadne dáta – začni v sekcii **Import dát**.")
        st.stop()

    snaps = st.session_state.snapshots
    prev_scores = None
    if snaps:
        opts = [f"{s['ts'].replace('T', ' ')} ({s.get('label') or 'bez popisu'}, {len(s['scores'])} akcií)"
                for s in snaps]
        c0, c1, c2 = st.columns([2, 2, 2])
        with c0:
            idx = st.selectbox("Porovnávať Δ voči snapshotu", range(len(snaps)),
                               index=len(snaps) - 1, format_func=lambda i: opts[i])
            prev_scores = snaps[idx]["scores"]
    else:
        c1, c2 = st.columns(2)

    with c1:
        layout = st.radio("Zobrazenie",
                          ["Všetky akcie spolu", "Podľa sekcií (portfóliá / watchlisty)"],
                          horizontal=True)
    with c2:
        sortmode = st.radio("Usporiadanie", ["Podľa hodnoty", "Podľa skóre", "Abecedne"],
                            horizontal=True)

    total = sum(e["value_eur"] for e in stocks if e.get("value_eur"))
    results = {e["symbol"]: compute_score(e, st.session_state.weights, st.session_state.params)
               for e in stocks}
    scored = [r["score"] for r in results.values() if r["score"] is not None]
    n_changed = 0
    if prev_scores is not None:
        for sym, r in results.items():
            if r["score"] is None:
                continue
            p = prev_scores.get(sym)
            if p is None or p["score"] != r["score"]:
                n_changed += 1

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Hodnota (ocenené pozície)", f"{fmt_eur(total)} €")
    m2.metric("Počet akcií", len(stocks))
    m3.metric("Priemerné skóre", round(sum(scored) / len(scored)) if scored else "–")
    m4.metric("Zmenené hodnotenia", n_changed if prev_scores is not None else "–")

    # najbližšie earnings (z Zacks feedu, confirmed_reporting_date MM/DD/YYYY)
    upcoming = []
    today = dt.date.today()
    for e in stocks:
        d = e.get("earnings_date")
        if not d:
            continue
        try:
            mm, dd, yy = d.split("/")
            ed = dt.date(int(yy), int(mm), int(dd))
        except Exception:
            continue
        days = (ed - today).days
        if 0 <= days <= 30:
            upcoming.append((days, ed, e["symbol"]))
    if upcoming:
        upcoming.sort()
        with st.expander(f"📅 Najbližšie výsledky (30 dní): {len(upcoming)} akcií"):
            st.markdown(" · ".join(
                f"**{sym}** {ed.strftime('%d.%m.')} ({days} d.)"
                for days, ed, sym in upcoming))

    if prev_scores is not None and n_changed:
        if st.checkbox("Zobraziť len akcie so zmenou hodnotenia"):
            changed_syms = set()
            for sym, r in results.items():
                if r["score"] is None:
                    continue
                p = prev_scores.get(sym)
                if p is None or p["score"] != r["score"]:
                    changed_syms.add(sym)
            stocks = [e for e in stocks if e["symbol"] in changed_syms]

    if layout.startswith("Všetky"):
        render_table(sort_entries(stocks, sortmode), total, prev_scores)
    else:
        groups = sorted({g for e in stocks for g in e.get("groups", [])})
        no_group = [e for e in stocks if not e.get("groups")]
        for g in groups:
            members = [e for e in stocks if g in e.get("groups", [])]
            if not members:
                continue
            gval = sum(e["value_eur"] for e in members if e.get("value_eur"))
            st.subheader(f"{g}  ·  {fmt_eur(gval)} € · {len(members)} akcií")
            render_table(sort_entries(members, sortmode), total, prev_scores)
        if no_group:
            st.subheader(f"(bez sekcie) · {len(no_group)} akcií")
            render_table(sort_entries(no_group, sortmode), total, prev_scores)

    st.caption("Skóre je orientačná syntéza verejných ratingov, nie investičné odporúčanie. "
               "`*` = neúplné skóre · modrá bodka a podfarbenie = zmena oproti zvolenému "
               "snapshotu · Δ „nová“ = akcia v snapshote nebola.")

# =============================================================== IMPORT
elif page == "📥 Import dát":
    st.title("Import dát")

    tab_pdf, tab_csv, tab_zx, tab_sws, tab_claude, tab_shot, tab_cons, tab_json = st.tabs(
        ["Trading 212 PDF", "Simply Wall St CSV", "Zacks online", "SWS online",
         "Claude export (CSV)", "Screenshoty cez API (voliteľné)",
         "Konsenzus analytikov", "Záloha (JSON)"])

    # ---- Claude export CSV (bezplatný screenshot workflow)
    with tab_claude:
        st.markdown(
            "**Bezplatný workflow pre screenshoty:** nahraj screenshoty (Zacks watchlist, "
            "SWS valuácie) do chatu s Claude a popros o export v tomto formáte. Vrátený "
            "CSV súbor sem nahraj – appka ho zmerguje s existujúcimi dátami.\n\n"
            "Formát: povinný stĺpec `ticker`, voliteľné `name, group, zacks_rank, value, "
            "growth, momentum, vgm, sws_fv_pct, snowflake (1-5 alebo green/lime/yellow/"
            "orange/red), analyst_target, consensus, industry_rank_pct, qty, currency, price, "
            "value_eur` (pozičné stĺpce: hodnota v EUR sa dopočíta kurzami z Nastavení). "
            "**Prázdne bunky sa ignorujú** – import nikdy neprepíše existujúce dáta prázdnom.")
        st.code("ticker,zacks_rank,vgm,sws_fv_pct,snowflake,analyst_target\n"
                "MSFT,3,B,30.5,green,562\n"
                "MU,1,C,-71.8,lime,\n"
                "HIMS,5,D,-854.4,orange,3.86", language="csv")
        ups_c = st.file_uploader("CSV z Claude", type="csv", accept_multiple_files=True,
                                 key="claude_csv")
        if ups_c and st.button("Importovať Claude export"):
            n, all_errs = 0, []
            for f in ups_c:
                rows, errs = parsers.parse_claude_csv(f.read())
                all_errs += errs
                for r in rows:
                    e = get_entry(r["ticker"])
                    if r.get("name"):
                        e["name"] = e["name"] or r["name"]
                    if r.get("group") and r["group"] not in e["groups"]:
                        e["groups"].append(r["group"])
                    for src, dst in (("zacks_rank", "zacks_rank"), ("vgm", "zacks_vgm"),
                                     ("value", "zacks_v"), ("growth", "zacks_g"),
                                     ("momentum", "zacks_m"), ("consensus", "consensus"),
                                     ("sws_fv_pct", "sws_fv_pct"),
                                     ("analyst_target", "analyst_target"),
                                     ("industry_rank_pct", "industry_rank_pct"),
                                     ("snowflake", "snow_level"),
                                     ("qty", "qty"), ("currency", "currency"),
                                     ("price", "price"), ("value_eur", "value_eur")):
                        if src in r:
                            e[dst] = r[src]
                    if "value_eur" not in r and all(k in r for k in ("qty", "currency", "price")):
                        v = value_in_eur(r["qty"], r["currency"], r["price"], st.session_state.fx)
                        if v is not None:
                            e["value_eur"] = round(v, 2)
                    n += 1
            save_store()
            st.success(f"Importovaných {n} riadkov.")
            for err in all_errs[:15]:
                st.caption(f"⚠ {err}")

    # ---- SWS online (grid API)
    with tab_sws:
        st.markdown(
            "**EXPERIMENTÁLNE:** stiahne snowflake osi (Value/Future/Past/Health/Dividend) "
            "z interného grid API Simply Wall St (`api.simplywall.st/api/grid/filter`). "
            "⚠️ **Overené 07/2026: endpoint je za Cloudflare bot ochranou a z bežných "
            "requestov vracia challenge stránku – táto cesta pravdepodobne nebude fungovať.** "
            "Pre SWS dáta používaj CSV export a screenshoty. Záložka ostáva pre prípad, "
            "že ochranu v budúcnosti uvoľnia. "
            "**Fair value % ani analyst target nevracia**, tie ostávajú na screenshotoch. "
            "Pri zlyhaní sa existujúce dáta (CSV/screenshoty) nemenia.")
        manual_s = st.text_input("Tickery (čiarkou oddelené; prázdne = všetky načítané akcie)",
                                 "", key="sws_manual")
        grp_s = st.text_input("Názov sekcie (voliteľné)", "", key="sws_grp")
        if st.button("⬇️ Stiahnuť SWS snowflake dáta"):
            syms = ([t.strip().upper() for t in manual_s.split(",") if t.strip()]
                    if manual_s.strip() else sorted(st.session_state.stocks.keys()))
            if not syms:
                st.warning("Žiadne tickery – importuj akcie alebo ich zadaj ručne.")
            else:
                prog = st.progress(0.0, text="Sťahujem...")
                rows, errs = [], []
                CHUNK = 10
                for i in range(0, len(syms), CHUNK):
                    r, e = parsers.fetch_sws_online(syms[i:i + CHUNK])
                    rows += r
                    errs += e
                    prog.progress(min(1.0, (i + CHUNK) / len(syms)),
                                  text=f"Sťahujem... {min(i + CHUNK, len(syms))}/{len(syms)}")
                prog.empty()
                for r in rows:
                    e = get_entry(r["ticker"])
                    e["sws_axes"] = r["sws_axes"]
                    e["name"] = e["name"] or r.get("name", "")
                    if grp_s and grp_s not in e["groups"]:
                        e["groups"].append(grp_s)
                save_store()
                st.success(f"Aktualizovaných {len(rows)} akcií, {len(errs)} chýb.")
                for err in errs[:20]:
                    st.caption(f"⚠ {err}")
                if len(errs) > 20:
                    st.caption(f"... a ďalších {len(errs) - 20} chýb.")

    # ---- Zacks online (quote-feed)
    with tab_zx:
        st.markdown(
            "Stiahne **Zacks Rank** priamo z verejného quote feedu Zacks "
            "(`quote-feed.zacks.com`) pre zadané alebo všetky načítané tickery. "
            "Ide o neoficiálny endpoint – môže sa kedykoľvek zmeniť. "
            "**Style scores (VGM) feed neobsahuje**, tie sa naďalej dopĺňajú zo screenshotov. "
            "Európske tickery je potrebné mať v ADR podobe (VWAGY, RNMBY, NVO...).")
        manual = st.text_input("Tickery (čiarkou oddelené; prázdne = všetky načítané akcie)", "")
        try_styles = st.checkbox(
            "Skúsiť stiahnuť aj style scores (V/G/M/VGM) a industry rank z quote stránky "
            "– EXPERIMENTÁLNE, stránka má bot ochranu", value=False)
        if st.button("⬇️ Stiahnuť Zacks dáta"):
            syms = ([t.strip().upper() for t in manual.split(",") if t.strip()]
                    if manual.strip() else sorted(st.session_state.stocks.keys()))
            if not syms:
                st.warning("Žiadne tickery – importuj akcie alebo ich zadaj ručne.")
            else:
                prog = st.progress(0.0, text="Sťahujem...")
                rows, errs = [], []
                CHUNK = 10
                for i in range(0, len(syms), CHUNK):
                    r, e = parsers.fetch_zacks_online(syms[i:i + CHUNK])
                    rows += r
                    errs += e
                    prog.progress(min(1.0, (i + CHUNK) / len(syms)),
                                  text=f"Sťahujem... {min(i + CHUNK, len(syms))}/{len(syms)}")
                prog.empty()
                changed = []
                for r in rows:
                    e = get_entry(r["ticker"])
                    old = e.get("zacks_rank")
                    if old and base(old) != r["zacks_rank"]:
                        changed.append(f'{r["ticker"]}: {base(old)} → {r["zacks_rank"]}')
                    e["zacks_rank"] = r["zacks_rank"]
                    e["name"] = e["name"] or r.get("name", "")
                    if r.get("earnings_date"):
                        e["earnings_date"] = r["earnings_date"]
                    if r.get("pe_f1"):
                        e["pe_f1"] = r["pe_f1"]
                n_styles = 0
                if try_styles:
                    prog2 = st.progress(0.0, text="Sťahujem style scores...")
                    srows, serrs = [], []
                    for i in range(0, len(syms), CHUNK):
                        r2, e2 = parsers.fetch_zacks_style_scores(syms[i:i + CHUNK])
                        srows += r2
                        serrs += e2
                        prog2.progress(min(1.0, (i + CHUNK) / len(syms)),
                                       text=f"Style scores... {min(i + CHUNK, len(syms))}/{len(syms)}")
                    prog2.empty()
                    for r2 in srows:
                        e = get_entry(r2["ticker"])
                        e["zacks_v"], e["zacks_g"] = r2["value"], r2["growth"]
                        e["zacks_m"], e["zacks_vgm"] = r2["momentum"], r2["vgm"]
                        if r2.get("industry_rank_pct") is not None:
                            e["industry_rank_pct"] = r2["industry_rank_pct"]
                        n_styles += 1
                    errs += serrs
                save_store()
                st.success(f"Aktualizovaných {len(rows)} rankov"
                           + (f" a {n_styles} style scores" if try_styles else "")
                           + f", {len(errs)} chýb.")
                if changed:
                    st.info("Zmeny rankov: " + "; ".join(changed))
                for err in errs[:20]:
                    st.caption(f"⚠ {err}")
                if len(errs) > 20:
                    st.caption(f"... a ďalších {len(errs) - 20} chýb.")

    with tab_pdf:
        st.markdown("Nahraj **Confirmation of holdings** PDF z Trading 212. "
                    "Hodnoty sa prepočítajú do EUR kurzami z Nastavení.")
        grp = st.text_input("Názov sekcie pre tieto pozície", "T212 portfólio")
        up = st.file_uploader("PDF súbor", type="pdf")
        if up and st.button("Spracovať PDF"):
            rows, tot = parsers.parse_t212_pdf(up.read())
            if not rows:
                st.error("V PDF sa nepodarilo nájsť žiadne pozície – skontroluj formát.")
            else:
                st.session_state.pdf_rows = rows
                st.success(f"Načítaných {len(rows)} pozícií"
                           + (f", deklarovaná hodnota {tot}" if tot else ""))
        if "pdf_rows" in st.session_state:
            st.markdown("**Priraď tickery** (návrhy z už načítaných dát; pohodlnejšia cesta: "
                        "nahraj PDF do chatu s Claude a importuj vrátený CSV cez záložku "
                        "Claude export). Riadky s prázdnym tickerom sa neuložia.")
            dfm = pd.DataFrame([{
                "Názov": r["name"],
                "Ticker": suggest_symbol(r["name"], st.session_state.stocks),
                "Množstvo": r["qty"], "Mena": r["currency"], "Cena": r["price"],
            } for r in st.session_state.pdf_rows])
            edited = st.data_editor(dfm, num_rows="fixed", use_container_width=True,
                                    key="pdf_map")
            if st.button("Uložiť pozície do dát"):
                fx = st.session_state.fx
                n_ok = 0
                for _, r in edited.iterrows():
                    sym = str(r["Ticker"]).strip().upper()
                    if not sym or sym == "NAN":
                        continue
                    e = get_entry(sym)
                    e["name"] = e["name"] or r["Názov"]
                    e["qty"], e["currency"], e["price"] = r["Množstvo"], r["Mena"], r["Cena"]
                    e["value_eur"] = value_in_eur(r["Množstvo"], r["Mena"], r["Cena"], fx)
                    if grp not in e["groups"]:
                        e["groups"].append(grp)
                    n_ok += 1
                save_store()
                st.success(f"Uložených {n_ok} pozícií do sekcie \u201e{grp}\u201c. "
                           "Riadky bez tickeru boli preskočené.")

    with tab_csv:
        st.markdown("CSV export portfólia/watchlistu zo Simply Wall St "
                    "(obsahuje snowflake osi Value/Future/Past/Health/Dividend).")
        grp2 = st.text_input("Názov sekcie", "SWS watchlist")
        ups = st.file_uploader("CSV súbory", type="csv", accept_multiple_files=True)
        if ups and st.button("Spracovať CSV"):
            n = 0
            for f in ups:
                for r in parsers.parse_sws_csv(f.read()):
                    e = get_entry(r["symbol"])
                    e["name"] = r["name"] or e["name"]
                    e["sws_axes"] = r["sws_axes"]
                    if grp2 not in e["groups"]:
                        e["groups"].append(grp2)
                    n += 1
            save_store()
            st.success(f"Spracovaných {n} riadkov do sekcie \u201e{grp2}\u201c.")

    with tab_shot:
        st.markdown("**Voliteľná alternatíva** k záložke Claude export: screenshoty číta "
                    "Claude API priamo z appky (platené za tokeny, rádovo centy). Kľúč sa "
                    "berie zo `st.secrets['ANTHROPIC_API_KEY']`, alebo ho zadaj nižšie.")
        try:
            secret_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            secret_key = ""
        api_key = secret_key or st.text_input("Anthropic API kľúč", type="password")
        kind = st.radio("Typ screenshotov",
                        ["Zacks (rank + style scores)",
                         "Simply Wall St (fair value + snowflake)"], horizontal=True)
        grp3 = st.text_input("Názov sekcie (voliteľné – ak ide o watchlist)", "")
        shots = st.file_uploader("PNG/JPG screenshoty", type=["png", "jpg", "jpeg"],
                                 accept_multiple_files=True)
        if shots and api_key and st.button("Vyťažiť dáta zo screenshotov"):
            imgs = [(f.name, f.read(), f.type or "image/png") for f in shots]
            k = "zacks" if kind.startswith("Zacks") else "sws"
            with st.spinner("Claude číta screenshoty..."):
                rows, errs = parsers.extract_from_screenshots(imgs, k, api_key)
            for err in errs:
                st.warning(err)
            n = 0
            for r in rows:
                sym = str(r.get("ticker", "")).strip().upper()
                if not sym:
                    continue
                e = get_entry(sym)
                if k == "zacks":
                    e["zacks_rank"] = r.get("zacks_rank")
                    e["zacks_v"], e["zacks_g"] = r.get("value"), r.get("growth")
                    e["zacks_m"], e["zacks_vgm"] = r.get("momentum"), r.get("vgm")
                else:
                    e["sws_fv_pct"] = r.get("fv_pct")
                    e["snow_level"] = parsers.SNOW_COLOR_TO_LEVEL.get(r.get("snowflake_color"))
                    e["analyst_target"] = r.get("analyst_target")
                if grp3 and grp3 not in e["groups"]:
                    e["groups"].append(grp3)
                n += 1
            save_store()
            st.success(f"Vyťažených {n} riadkov. Skontroluj ich v sekcii Úprava dát.")

    with tab_cons:
        st.markdown("Konsenzus analytikov sa zadáva ručne (Strong Buy / Buy / Hold / Sell).")
        if st.session_state.stocks:
            dfc = pd.DataFrame([{"Ticker": k, "Firma": v.get("name", ""),
                                 "Konsenzus": v.get("consensus") or ""}
                                for k, v in sorted(st.session_state.stocks.items())])
            edited = st.data_editor(
                dfc, use_container_width=True, num_rows="fixed", key="cons_edit",
                column_config={"Konsenzus": st.column_config.SelectboxColumn(
                    options=["", "Strong Buy", "Buy", "Hold", "Sell", "bez dát"])})
            if st.button("Uložiť konsenzus"):
                for _, r in edited.iterrows():
                    st.session_state.stocks[r["Ticker"]]["consensus"] = r["Konsenzus"] or None
                save_store()
                st.success("Konsenzus uložený.")
        else:
            st.info("Najprv importuj akcie.")

    with tab_json:
        st.markdown("Lokálna pamäť je v `data/store.json`. Na Streamlit Cloud sa po "
                    "reštarte kontajnera maže – **exportuj si zálohu** (obsahuje aj snapshoty).")
        payload = json.dumps({
            "stocks": st.session_state.stocks,
            "weights": st.session_state.weights,
            "params": st.session_state.params,
            "fx": st.session_state.fx,
            "snapshots": st.session_state.snapshots,
            "auto_snapshot": st.session_state.auto_snapshot,
        }, ensure_ascii=False, indent=1)
        st.download_button("⬇️ Stiahnuť zálohu (JSON)", payload,
                           file_name="portfolio_synteza_data.json")
        rest = st.file_uploader("Obnoviť zo zálohy", type="json")
        if rest and st.button("Obnoviť dáta"):
            d = json.loads(rest.read())
            st.session_state.stocks = d.get("stocks", {})
            st.session_state.weights = d.get("weights", dict(DEFAULT_WEIGHTS))
            st.session_state.params = {**DEFAULT_PARAMS, **d.get("params", {})}
            st.session_state.fx = d.get("fx", st.session_state.fx)
            st.session_state.snapshots = d.get("snapshots", [])
            st.session_state.auto_snapshot = d.get("auto_snapshot", True)
            save_store()
            st.success(f"Obnovených {len(st.session_state.stocks)} akcií "
                       f"a {len(st.session_state.snapshots)} snapshotov.")

# =============================================================== ÚPRAVA
elif page == "✏️ Úprava dát":
    st.title("Úprava dát")
    if not st.session_state.stocks:
        st.info("Žiadne dáta – začni v Import dát.")
        st.stop()
    df = pd.DataFrame([{
        "Ticker": k, "Firma": v.get("name", ""),
        "Sekcie": ", ".join(v.get("groups", [])),
        "Hodnota €": v.get("value_eur"),
        "Zacks": v.get("zacks_rank") or "", "VGM": v.get("zacks_vgm") or "",
        "SWS FV %": v.get("sws_fv_pct"),
        "Snowflake (1-5)": v.get("snow_level"),
        "Konsenzus": v.get("consensus") or "",
        "Zmazať": False,
    } for k, v in sorted(st.session_state.stocks.items())])
    edited = st.data_editor(df, use_container_width=True, num_rows="fixed", key="edit_all")
    if st.button("Uložiť zmeny"):
        for _, r in edited.iterrows():
            k = r["Ticker"]
            if r["Zmazať"]:
                st.session_state.stocks.pop(k, None)
                continue
            e = st.session_state.stocks[k]
            e["name"] = r["Firma"]
            e["groups"] = [g.strip() for g in str(r["Sekcie"]).split(",") if g.strip()]
            e["value_eur"] = None if pd.isna(r["Hodnota €"]) else float(r["Hodnota €"])
            e["zacks_rank"] = r["Zacks"] or None
            e["zacks_vgm"] = r["VGM"] or None
            e["sws_fv_pct"] = None if pd.isna(r["SWS FV %"]) else float(r["SWS FV %"])
            e["snow_level"] = None if pd.isna(r["Snowflake (1-5)"]) else int(r["Snowflake (1-5)"])
            e["consensus"] = r["Konsenzus"] or None
        save_store()
        st.success("Zmeny uložené.")

# =============================================================== NASTAVENIA
else:
    st.title("Nastavenia a metodika")
    st.markdown(scoring.METHODOLOGY_MD)
    st.markdown("---")

    st.subheader("Váhy komponentov")
    w = st.session_state.weights
    labels = [("zacks_rank", "Zacks Rank"), ("zacks_vgm", "Zacks VGM"),
              ("sws_val", "SWS valuácia"), ("snowflake", "Snowflake"),
              ("consensus", "Konsenzus"), ("industry", "Industry Rank")]
    c = st.columns(len(labels))
    w.setdefault("industry", 0.0)
    for col, (key, lab) in zip(c, labels):
        w[key] = col.slider(lab, 0.0, 1.0, float(w[key]), 0.05)
    s = sum(w.values())
    if s == 0:
        st.error("Súčet váh nemôže byť 0.")
    else:
        st.caption(f"Súčet váh {s:.2f} – pri výpočte sa normalizuje na 1,00 "
                   f"({', '.join(f'{lab} {w[k]/s:.0%}' for k, lab in labels)})")

    st.subheader("Prahy vlajok a verdiktov")
    p = st.session_state.params
    c1, c2, c3 = st.columns(3)
    p["flag_underval"] = c1.number_input("Vlajky: prah podhodnotenia (%)", 10, 90,
                                         int(p["flag_underval"]))
    p["flag_overval"] = -c2.number_input("Vlajky: prah nadhodnotenia (%)", 10, 200,
                                         int(-p["flag_overval"]))
    p["snow_include_dividend"] = c3.checkbox("Snowflake: zahrnúť os Dividend",
                                             p["snow_include_dividend"])
    c4, c5, c6, c7 = st.columns(4)
    p["verdict_acc"] = c4.number_input("Akumulovať od", 50, 100, int(p["verdict_acc"]))
    p["verdict_hold_plus"] = c5.number_input("Držať + od", 30, 90, int(p["verdict_hold_plus"]))
    p["verdict_hold"] = c6.number_input("Držať od", 20, 80, int(p["verdict_hold"]))
    p["verdict_reduce"] = c7.number_input("Zvážiť redukciu od", 5, 60, int(p["verdict_reduce"]))

    st.subheader("Pamäť a snapshoty")
    st.session_state.auto_snapshot = st.checkbox(
        "Automatický snapshot pri prvom otvorení dňa (zachytí stav z minula pred novými zmenami)",
        st.session_state.auto_snapshot)
    if st.session_state.snapshots:
        st.caption(f"Uložených snapshotov: {len(st.session_state.snapshots)} (max 30). "
                   "Δ v Prehľade sa počíta voči zvolenému snapshotu.")
        if st.button("🗑 Vymazať všetky snapshoty"):
            st.session_state.snapshots = []
            save_store()
            st.success("Snapshoty vymazané.")

    st.subheader("Menové kurzy (prevod do EUR)")
    fx = st.session_state.fx
    c8, c9, c10 = st.columns(3)
    fx["EURUSD"] = c8.number_input("EUR/USD", 0.5, 2.0, float(fx["EURUSD"]), format="%.4f")
    fx["EURGBP"] = c9.number_input("EUR/GBP", 0.5, 2.0, float(fx["EURGBP"]), format="%.4f")
    fx["EURCAD"] = c10.number_input("EUR/CAD", 0.5, 3.0, float(fx["EURCAD"]), format="%.4f")
    if st.button("Prepočítať hodnoty pozícií novými kurzami"):
        n = 0
        for e in st.session_state.stocks.values():
            if e.get("qty") is not None:
                e["value_eur"] = value_in_eur(e["qty"], e["currency"], e["price"], fx)
                n += 1
        save_store()
        st.success(f"Prepočítaných {n} pozícií.")

    if st.button("↩︎ Obnoviť defaultné váhy a prahy"):
        st.session_state.weights = dict(DEFAULT_WEIGHTS)
        st.session_state.params = dict(DEFAULT_PARAMS)
        save_store()
        st.rerun()

    if st.button("💾 Uložiť nastavenia"):
        save_store()
        st.success("Nastavenia uložené.")
