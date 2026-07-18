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

- **TQQQ** in confirmed uptrends (adaptive Ichimoku structure + 20-day EMA, ~13 blockers all clear)
- **SQQQ** in confirmed downtrends (bear structure + QQQ under its 200-day SMA), with a −10% hard stop
- **Cash** whenever neither side fully aligns (~26% of days)
- Exits are **structural** (trend break, VXN crash-spike, 20% trailing stop) — never "it looks overbought"
- Signals finalize on the **daily close**; orders execute at the **next market open**. No repainting.

All figures are from a backtest on real prices with next-open fills and slippage.
**Not investment advice.** Past performance is not indicative of future results.
