"""
build_ohlc.py — generate the daily candlestick JSONs for the QQQ Swing Strategy dashboard.

Self-contained: fetches daily Open/High/Low/Close from Yahoo (public data) for
TQQQ (the chart's primary instrument), SQQQ, and the toggle/benchmark tickers
QLD / QID / QQQ / PSQ. No strategy logic or parameters here.

Output format (compact, date-keyed):
  [ ["YYYY-MM-DD", open, high, low, close], ... ]

Run:
    python build_ohlc.py
"""
from __future__ import annotations
import json, urllib.request, urllib.parse
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                       # pragma: no cover
    _ET = None


def _et_now():
    now = datetime.now(tz=timezone.utc)
    return now.astimezone(_ET) if _ET else now


def drop_forming_today(rows):
    """Drop today's bar only when it's a degenerate flat placeholder
    (open==high==low==close) — the empty candle Yahoo emits before any
    real prints arrive."""
    if not rows:
        return rows
    et = _et_now()
    today = et.strftime("%Y-%m-%d")
    last = rows[-1]
    if last[0] == today and last[1] == last[2] == last[3] == last[4]:
        return rows[:-1]
    return rows


def intraday_today(symbol):
    """Rebuild today's OHLC from the 5-min intraday series — Yahoo's *daily* bar
    carries a glitchy/stale open early in the session. includePrePost=true so the
    candle forms from pre-market (~4am ET) through after-hours (~8pm ET)."""
    et = _et_now(); today = et.strftime("%Y-%m-%d")
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
               f"?range=1d&interval=5m&includePrePost=true")
        res = json.loads(_get(url, timeout=15))["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        o, h, l, c = q["open"], q["high"], q["low"], q["close"]
        oo = hh = ll = cc = None
        for i, t in enumerate(ts):
            d = datetime.fromtimestamp(t, tz=_ET).strftime("%Y-%m-%d") if _ET else \
                datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            if d != today or None in (o[i], h[i], l[i], c[i]):
                continue
            if oo is None:
                oo = o[i]
            hh = h[i] if hh is None else max(hh, h[i])
            ll = l[i] if ll is None else min(ll, l[i])
            cc = c[i]
        if oo is None:
            return None
        return [today, round(oo, 4), round(hh, 4), round(ll, 4), round(cc, 4)]
    except Exception as e:
        print(f"  intraday {symbol} FAILED: {e}")
        return None

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def _get(url, timeout=30, extra=None):
    h = {**HDRS, **(extra or {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        import gzip
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data

def fetch_ohlc(symbol="TQQQ", start="2010-02-11"):
    """Split+dividend-adjusted daily OHLC (matches the backtest engine's basis)."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request("https://finance.yahoo.com/", headers=HDRS), timeout=10) as r:
            cookie = r.headers.get("Set-Cookie", "").split(";")[0]
    except Exception:
        cookie = ""
    t1 = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    t2 = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={t1}&period2={t2}&interval=1d")
    data = json.loads(_get(url, extra={"Cookie": cookie} if cookie else None))
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    o, h, l, c = q["open"], q["high"], q["low"], q["close"]
    rows = []
    for i, t in enumerate(ts):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        fac = (adj[i] / c[i]) if (adj and adj[i] and c[i]) else 1.0
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append([d, round(o[i]*fac, 4), round(h[i]*fac, 4),
                     round(l[i]*fac, 4), round(c[i]*fac, 4)])
    return rows

def main():
    # TQQQ/SQQQ from inception (2010-02) + QQQ for market context.
    for sym, fname in [("TQQQ", "tqqq_ohlc.json"), ("SQQQ", "sqqq_ohlc.json"),
                       ("QQQ",  "qqq_ohlc.json"),  ("SPY",  "spy_ohlc.json")]:
        try:
            rows = drop_forming_today(fetch_ohlc(sym))
            # Replace today's (glitchy) daily bar with one rebuilt from 5-min prints.
            today = _et_now().strftime("%Y-%m-%d")
            itd = intraday_today(sym)
            if itd:
                if rows and rows[-1][0] == today:
                    # keep the adjusted basis: intraday prints are unadjusted, but for
                    # the CURRENT day adjclose==close, so they're the same basis.
                    rows[-1] = itd
                else:
                    rows.append(itd)
        except Exception as e:
            print(f"  {sym} FAILED: {e}")
            continue
        with open(fname, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, separators=(",", ":"))
        if rows:
            print(f"Wrote {fname}: {len(rows)} bars "
                  f"({rows[0][0]} .. {rows[-1][0]}), last close={rows[-1][4]}")
        else:
            print(f"Wrote {fname}: EMPTY")

if __name__ == "__main__":
    main()
