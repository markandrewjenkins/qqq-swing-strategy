# QQQ Swing Strategy — Live Dashboard

Public, auto-updating dashboard for a leveraged Nasdaq-100 trend-following swing
strategy (TQQQ / SQQQ / cash), presented in a beige-and-ink "vaporwave etch-a-sketch"
theme. Companion piece to the
[VIX Swing Strategy](https://markandrewjenkins.github.io/vix-swing-strategy/) dashboard.

**Live page:** https://markandrewjenkins.github.io/qqq-swing-strategy/

## What's in this repo

| File | Purpose |
|---|---|
| `index.html` | The entire dashboard — one self-contained page (HTML/CSS/JS inline). |
| `backtest_results.json` | Historical signals, trades, equity curve, per-bar indicator readings. Produced by the **private** engine repo and pushed here on a schedule. |
| `live_status.json` | Live quotes, current position, derived readings. Produced by `update_live.py`. |
| `*_ohlc.json` | Daily candles (TQQQ, SQQQ, QLD, QID, QQQ, PSQ) incl. today's forming bar. Produced by `build_ohlc.py`. |
| `.github/workflows/update-live.yml` | Cloud cron: refreshes the candles + live status and commits them. |

The strategy engine, its parameters, and the backtest logic live in a separate
**private** repository — only the generated results file is published here.

## The strategy (short version)

Born as a TradingView Pine script ("Ichimoku+++, optimized for TQQQ"), interrogated
line by line, ported to Python on daily bars, de-bugged and de-overfit:

- **TQQQ** whenever it closes above its 20-day EMA (and the VIX curve isn't deeply backwardated) — invested ~92% of days
- **Exits are regime-gated:** while QQQ holds its 200-day SMA, dips are ridden; only a VXN crash-spike
  (99.5th pct) or a 40% catastrophe trail exits. Below the 200-day, the adaptive Ichimoku structure
  (bearish price bar / bearish Chikou) closes the position
- **SQQQ** in confirmed downtrends (bear structure + QQQ under its 200-day SMA), half-size, −10% hard stop
- Signals finalize on the **daily close**; orders execute at the **next market open**. No repainting.
- Backtested vs TQQQ buy-and-hold over the same window: ~2× the terminal wealth with a ~33-point
  smaller max drawdown.

All figures are from a backtest on real prices with next-open fills and slippage.
**Not investment advice.** Past performance is not indicative of future results.
