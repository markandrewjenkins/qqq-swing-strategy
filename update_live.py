"""
update_live.py — live market-state generator for the QQQ Swing Strategy dashboard
==================================================================================
Writes `live_status.json`, consumed by index.html and refreshed on a schedule
by the GitHub Action (and polled client-side every 60s while the page is open).

PRIVACY NOTE
------------
This script is intentionally self-contained and contains NO strategy parameters
and NO entry/exit logic. It publishes only:
  • public CBOE VXN/VIX/VIX3M end-of-day values,
  • live index + ETF quotes (Yahoo, intraday),
  • generic, non-proprietary derived readings (VIX contango %, 10Y−2Y spread),
  • the strategy's LAST OFFICIAL position, read straight from
    backtest_results.json (produced privately by the backtest engine).

Data sources (all public):
  CBOE CDN  — VXN, VIX, VIX3M daily history CSVs
  Yahoo v8  — ^VXN, ^VIX, ^VIX3M, ^NDX, TQQQ, SQQQ, QLD, QID, QQQ, PSQ
  FRED      — DGS2 / DGS10 (10Y−2Y spread; skipped gracefully when down)

Run:
    python update_live.py            # writes live_status.json
"""

from __future__ import annotations

import io, json, os, urllib.request, urllib.parse
from datetime import datetime, timezone

import pandas as pd

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                       # pragma: no cover
    _ET = None


def et_now() -> datetime:
    now = datetime.now(tz=timezone.utc)
    return now.astimezone(_ET) if _ET else now


def load_prev(path: str = "live_status.json") -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as e:
        print(f"  prev live_status.json read FAILED: {e}")
    return {}


HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str, timeout: int = 20, extra: dict | None = None) -> bytes:
    h = {**HDRS, **(extra or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        import gzip as gz
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gz.decompress(data)
        return data


# ── CBOE end-of-day prints ────────────────────────────────────────────────────
def cboe_last(symbol: str) -> tuple[float | None, float | None, str | None]:
    """Return (last_close, prev_close, iso_date) for a CBOE index history CSV."""
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
    try:
        text = _get(url).decode("utf-8", errors="replace")
        lines = text.strip().splitlines()
        hdr = next(i for i, l in enumerate(lines) if "DATE" in l.upper())
        df = pd.read_csv(io.StringIO("\n".join(lines[hdr:])))
        df.columns = [c.strip().upper() for c in df.columns]
        dc = next(c for c in df.columns if "DATE" in c)
        cc_candidates = [c for c in df.columns if "CLOSE" in c] or \
                        [c for c in df.columns if c != dc]
        cc = cc_candidates[0]
        df[dc] = pd.to_datetime(df[dc], errors="coerce")
        df = df.dropna(subset=[dc]).set_index(dc).sort_index()
        s = pd.to_numeric(df[cc], errors="coerce").dropna()
        if s.empty:
            return None, None, None
        prev = float(s.iloc[-2]) if len(s) >= 2 else None
        return float(s.iloc[-1]), prev, s.index[-1].date().isoformat()
    except Exception as e:
        print(f"  cboe  {symbol:6s} FAILED: {e}")
        return None, None, None


# ── FRED (EOD; graceful skip) ─────────────────────────────────────────────────
def fred_last(series_id: str) -> float | None:
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=2025-01-01"
        df = pd.read_csv(io.StringIO(_get(url, timeout=25).decode()))
        df.columns = ["date", "value"]
        s = pd.to_numeric(df["value"], errors="coerce").dropna()
        return float(s.iloc[-1]) if not s.empty else None
    except Exception as e:
        print(f"  fred  {series_id:6s} FAILED: {e}")
        return None


# ── Yahoo v8 live quote ───────────────────────────────────────────────────────
def _et_bar(ts):
    """(ET date string, minutes-since-midnight ET) for an epoch timestamp."""
    dt = (datetime.fromtimestamp(ts, tz=_ET) if _ET
          else datetime.fromtimestamp(ts, tz=timezone.utc))
    return dt.strftime("%Y-%m-%d"), dt.hour * 60 + dt.minute


_RTH_OPEN, _RTH_CLOSE = 9 * 60 + 30, 16 * 60      # 9:30 / 16:00 ET


def yahoo_quote(symbol: str, prepost: bool = False) -> dict:
    """Session-aware quote following the standard market convention.

    Built from a 5-day 5-minute series so we know each session's real close:
      • Regular hours → price = live regular print, % = vs the PRIOR regular close.
      • After-hours   → price/% stay frozen at today's regular close vs the prior
                        close (the day's official change); the AH move is a
                        SEPARATE number measured from *today's* close.
      • Pre-market    → today hasn't traded regular yet, so price/% show the LAST
                        COMPLETED session (yesterday's close and its own daily
                        change); the pre-market move is the separate number,
                        measured from yesterday's close.
    That last rule is the fix for the pre-market reading previously duplicating
    the headline quote.

    Emitted fields:
      price / change_pct   the headline pair (always internally consistent)
      prev_close           the regular close the headline % is measured against
      session              'pre' | 'regular' | 'post' | 'closed'
      ext_price/ext_change extended-hours move vs its correct baseline
      asof_date            ET date of the reading shown as `price` (pairing/staleness)
      time                 ISO timestamp of the freshest print
    """
    try:
        try:
            with urllib.request.urlopen(
                urllib.request.Request("https://finance.yahoo.com/", headers=HDRS),
                timeout=10
            ) as r:
                cookie = r.headers.get("Set-Cookie", "").split(";")[0]
        except Exception:
            cookie = ""
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?range=5d&interval=5m"
               + ("&includePrePost=true" if prepost else ""))
        data = json.loads(_get(url, extra={"Cookie": cookie} if cookie else None))
        res  = data["chart"]["result"][0]
        ts   = res.get("timestamp") or []
        cl   = (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close")) or []

        grace = 15 if symbol.startswith("^") else 0
        reg_close, pre_last, post_last, reg_time = {}, {}, {}, {}
        last_t = last_date = last_tod = None
        for i, c in enumerate(cl):
            if c is None or i >= len(ts):
                continue
            t = ts[i]
            dstr, tod = _et_bar(t)
            last_t, last_date, last_tod = t, dstr, tod
            # Indices get a 15-minute settle grace: VXN/VIX3M publish 09:30-16:15
            # and VIX 03:15-16:10, so their post-4pm prints are the closing settle,
            # not after-hours trading. ETFs genuinely trade from 16:00, so no grace.
            if _RTH_OPEN <= tod <= _RTH_CLOSE + grace:
                reg_close[dstr] = c; reg_time[dstr] = t
            elif tod < _RTH_OPEN:
                pre_last[dstr] = c
            else:
                post_last[dstr] = c

        rdates = sorted(reg_close)
        if not rdates:
            raise ValueError("no regular-session bars")

        # Which session are we in, per the freshest print?
        today = last_date
        has_reg_today = today in reg_close
        if last_t is None:
            session = "closed"
        elif has_reg_today and _RTH_OPEN <= last_tod <= _RTH_CLOSE + grace:
            session = "regular"
        elif last_tod is not None and last_tod < _RTH_OPEN and not has_reg_today:
            session = "pre"
        elif last_tod is not None and last_tod > _RTH_CLOSE + grace and has_reg_today:
            session = "post"
        else:
            session = "regular" if has_reg_today else "closed"

        def _chg(a, b):
            return (a / b - 1.0) if (a and b) else None

        if session in ("regular", "post"):
            cur_d  = rdates[-1]
            prev_d = rdates[-2] if len(rdates) >= 2 else None
            price  = reg_close[cur_d]
            prev   = reg_close[prev_d] if prev_d else None
            chg    = _chg(price, prev)
            asof   = cur_d
            ext_px = post_last.get(today) if session == "post" else None
            ext_chg = _chg(ext_px, price) if ext_px else None
        else:
            # pre-market or closed → show the last COMPLETED regular session
            cur_d  = rdates[-1]
            prev_d = rdates[-2] if len(rdates) >= 2 else None
            price  = reg_close[cur_d]
            prev   = reg_close[prev_d] if prev_d else None
            chg    = _chg(price, prev)
            asof   = cur_d
            ext_px = pre_last.get(today) if session == "pre" else None
            ext_chg = _chg(ext_px, price) if ext_px else None

        r6 = lambda v: round(v, 6) if v is not None else None
        r4 = lambda v: round(v, 4) if v is not None else None
        return {
            "price": r4(price), "prev_close": r4(prev), "change_pct": r6(chg),
            "session": session, "asof_date": asof,
            "regular_price": r4(price), "regular_change": r6(chg),
            "ext_price": r4(ext_px), "ext_change": r6(ext_chg),
            "reg_time": (datetime.fromtimestamp(reg_time.get(asof), tz=timezone.utc).isoformat()
                         if reg_time.get(asof) else None),
            "time": (datetime.fromtimestamp(last_t, tz=timezone.utc).isoformat()
                     if last_t else None),
        }
    except Exception as e:
        print(f"  yahoo {symbol:6s} FAILED: {e}")
        return {"price": None, "prev_close": None, "change_pct": None,
                "session": None, "asof_date": None,
                "regular_price": None, "regular_change": None,
                "ext_price": None, "ext_change": None, "reg_time": None, "time": None}


# ── Last official position from the (privately generated) backtest ───────────
def last_official(path: str = "backtest_results.json") -> dict:
    """Surface the strategy's last official position + decision from the final
    bar of the backtest's bar_history. No logic is re-derived here."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            res = json.load(fh)
        bars = res.get("bar_history") or []
        if not bars:
            return {}
        b = bars[-1]
        # Entry anchor of the currently-open position: walk back over the
        # trailing run of same-position bars for the entry date/price, so we
        # can compute a LIVE % return (entry → live quote).
        entry_price, entry_date = None, None
        pos = b.get("position")
        if pos and pos != "CASH":
            i = len(bars) - 1
            start = bars[i]
            while i >= 0 and bars[i].get("position") == pos:
                start = bars[i]
                i -= 1
            entry_date = start.get("date")
            entry_price = (start.get("tqqq_price") if pos == "LONG_TQQQ"
                           else start.get("sqqq_price"))
        return {
            "date":        b.get("date"),
            "position":    pos,
            "signal":      b.get("signal"),
            "open_pnl":    b.get("open_pnl_pct"),
            "equity":      b.get("equity"),
            "entry_date":  entry_date,
            "entry_price": entry_price,
        }
    except Exception as e:
        print(f"  backtest_results.json read FAILED: {e}")
        return {}


def _live_official(quotes: dict) -> dict:
    """last_official() + a LIVE open P&L (entry price → current quote)."""
    o = last_official()
    pos, ep = o.get("position"), o.get("entry_price")
    if pos and pos != "CASH" and ep:
        sym = "tqqq" if pos == "LONG_TQQQ" else "sqqq"
        px = (quotes.get(sym) or {}).get("price")
        if px:
            o["open_pnl"] = round(px / ep - 1.0, 6)
            o["open_pnl_live"] = True
    return o


def main() -> None:
    print("Fetching live market state ...")

    prev = load_prev()
    prev_curve = ((prev.get("market") or {}).get("curve")) or {}
    now_iso = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    # ── Re-fetch the CBOE EOD prints only when a fresh one can exist ──────────
    # (posted ~5:30pm ET; intraday the CSVs still show yesterday's close)
    et = et_now()
    after_eod_post = (et.hour > 17) or (et.hour == 17 and et.minute >= 30)
    have_cached = any(prev_curve.get(k) is not None for k in ("vxn", "vix3m"))
    refresh_cboe = (not have_cached) or after_eod_post

    today_iso = et.date().isoformat()
    curve = {}
    if refresh_cboe:
        for key, sym in [("vxn", "VXN"), ("vix", "VIX"), ("vix3m", "VIX3M")]:
            val, pv, dt = cboe_last(sym)
            curve[key] = val
            curve[key + "_date"] = dt
            curve[key + "_chg"] = round(val / pv - 1.0, 6) if (val and pv) else None
            curve[key + "_ref"] = pv if (dt == today_iso) else val
            print(f"  cboe  {sym:6s} {val}")
    else:
        curve = dict(prev_curve)
        print(f"  cboe  reused cached EOD prints "
              f"(date={curve.get('vxn_date')}, ET={et.strftime('%H:%M')})")

    # Reference close for TODAY's intraday %change (see the VIX project for the
    # rationale — the cached close IS yesterday's close once dt != today).
    for key in ("vxn", "vix", "vix3m"):
        if curve.get(key) is None:
            continue
        dt, chg = curve.get(key + "_date"), curve.get(key + "_chg")
        if dt != today_iso:
            curve[key + "_ref"] = curve[key]
        elif curve.get(key + "_ref") is None and chg not in (None, -1):
            curve[key + "_ref"] = round(curve[key] / (1.0 + chg), 4)

    # ── Live quotes ───────────────────────────────────────────────────────────
    quotes = {}
    # VIX is disseminated through extended hours; VXN/VIX3M are regular-hours only
    # (so outside 9:30-16:00 ET they simply carry the last regular print).
    for sym in ["^VXN", "^VIX", "^VIX3M", "^NDX"]:
        quotes[sym.lower().lstrip("^")] = yahoo_quote(sym, prepost=True)
    for sym in ["TQQQ", "SQQQ", "QQQ", "SPY", "UPRO", "SPXU"]:
        quotes[sym.lower()] = yahoo_quote(sym, prepost=True)
    quotes["spx"] = yahoo_quote("^GSPC", prepost=False)   # S&P 500 index level
    # Re-base index %change on the authoritative CBOE prior close — but only for a
    # settled regular reading, so it never clobbers the pre/post-market convention.
    for qkey, ckey in [("vxn", "vxn"), ("vix", "vix"), ("vix3m", "vix3m")]:
        q = quotes.get(qkey); ref = curve.get(ckey + "_ref")
        if q and q.get("price") and ref and q.get("session") in ("regular", "post", "closed"):
            q["change_pct"] = round(q["price"] / ref - 1.0, 6)
            q["prev_close"] = round(ref, 4)

    # NDX freezes outside regular hours; QQQ trades ~4am-8pm — extrapolate the
    # index level from QQQ's % move when QQQ is the fresher quote.
    nx, qq = quotes.get("ndx"), quotes.get("qqq")
    if nx and qq and qq.get("change_pct") is not None and nx.get("prev_close") \
       and (not nx.get("time") or (qq.get("time") and qq["time"] > nx["time"])):
        nx["price"] = round(nx["prev_close"] * (1.0 + qq["change_pct"]), 2)
        nx["change_pct"] = qq["change_pct"]
        nx["time"] = qq["time"]

    # Live values override the EOD prints for the freshest reading.
    vxn  = quotes["vxn"]["price"];   vxn  = vxn  if vxn  is not None else curve.get("vxn")
    vix  = quotes["vix"]["price"];   vix  = vix  if vix  is not None else curve.get("vix")
    vix3 = quotes["vix3m"]["price"]; vix3 = vix3 if vix3 is not None else curve.get("vix3m")

    # ── Contango must compare VIX and VIX3M from the SAME session ────────────────
    # VIX updates through extended hours while VIX3M is regular-hours only, so a
    # naive vix3m/vix during pre-market mixes today's VIX with yesterday's VIX3M
    # and reports a bogus curve. Only use the live pair when both readings are
    # as-of the same trading date; otherwise fall back to the CBOE EOD pair (which
    # is internally consistent by construction) and flag it as not-live.
    a1 = (quotes.get("vix") or {}).get("asof_date")
    a3 = (quotes.get("vix3m") or {}).get("asof_date")
    if vix and vix3 and a1 and a3 and a1 == a3:
        contango = vix3 / vix - 1.0
        contango_live, contango_asof = True, a1
    elif curve.get("vix") and curve.get("vix3m"):
        contango = curve["vix3m"] / curve["vix"] - 1.0
        contango_live, contango_asof = False, curve.get("vix_date")
        print(f"  contango: VIX({a1}) / VIX3M({a3}) out of sync "
              f"-> using CBOE EOD pair ({contango_asof})")
    else:
        contango, contango_live, contango_asof = None, False, None
    regime = None
    if contango is not None:
        regime = "contango" if contango > 0 else "backwardation"

    # 10Y−2Y spread (FRED EOD, 1-day lag; carry forward the cached value if down)
    d10, d2 = fred_last("DGS10"), fred_last("DGS2")
    yc = round(d10 - d2, 3) if (d10 is not None and d2 is not None) else \
         ((prev.get("derived") or {}).get("yc_spread"))

    status = {
        "generated_utc": now_iso,
        "market": {
            "vxn_used":   round(vxn, 4)  if vxn  else None,
            "vix_used":   round(vix, 4)  if vix  else None,
            "vix3m_used": round(vix3, 4) if vix3 else None,
            "curve": curve,
            "quotes": quotes,
        },
        "derived": {
            "contango": round(contango, 6) if contango is not None else None,
            "contango_live": contango_live,     # False → VIX/VIX3M were out of
            "contango_asof": contango_asof,     #   sync; this is the EOD pair
            "yc_spread": yc,
            "regime": regime,
        },
        "cboe_refreshed": refresh_cboe,
        # Strategy's last OFFICIAL state (signals finalize on the daily close;
        # trades execute at the next market open — intraday readings indicative).
        "official": _live_official(quotes),
        "note": ("VXN/VIX/VIX3M are CBOE end-of-day (re-fetched only after the "
                 "~5:30pm ET post; cached intraday) with Yahoo intraday overrides. "
                 "ETF quotes are Yahoo intraday (~5-15 min delayed). Signals "
                 "finalize on the daily close and trade the next market open."),
    }

    with open("live_status.json", "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)
    print(f"Wrote live_status.json  (regime={regime}, "
          f"contango={status['derived']['contango']}, cboe_refreshed={refresh_cboe})")


if __name__ == "__main__":
    main()
