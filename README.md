# QQQ Swing Strategy — Live Dashboard

Public, auto-updating dashboard for a leveraged Nasdaq-100 trend-following swing
strategy (TQQQ / SQQQ / cash). Companion piece to the
[VIX Swing Strategy](https://markandrewjenkins.github.io/vix-swing-strategy/) dashboard.

**Live page:** https://markandrewjenkins.github.io/qqq-swing-strategy/

## What's in this repo

| File | Purpose |
|---|---|
| `index.html` | The entire dashboard — one self-contained page (HTML/CSS/JS inline). |
| `backtest_results.json` | Historical signals, trades, equity curve, per-bar indicator readings. Produced by the **private** engine repo and pushed here after each market close. |
| `live_status.json` | Live quotes, current position and generic derived readings. Produced by `update_live.py`. |
| `*_ohlc.json` | Daily candles (TQQQ, SQQQ, QQQ, SPY), including today's forming bar. Produced by `build_ohlc.py`. |
| `.github/workflows/update-live.yml` | Cloud job: refreshes the candles and live status through the session and commits them. |

The strategy engine, its parameters and the backtest logic live in a separate
**private** repository — only the generated results are published here.

## The strategy (short version)

It began as a TradingView Pine Script strategy, then was ported to Python on daily
bars and re-tested rule by rule:

- **Long TQQQ** in uptrends, with a deliberately simple entry.
- **Regime-gated exits:** in a bull regime, pullbacks are held and only a volatility
  crash-spike or a deep catastrophe trail forces an exit; in a bear regime, the
  trend structure decides.
- **SQQQ** only in confirmed downtrends, at reduced size, with trailing and hard stops.
- Signals finalize on the **daily close**; orders execute at the **next market open**,
  with slippage modelled. No repainting.

All figures on the dashboard come from a backtest on real ETF prices. The rules were
refined on the same history they are evaluated on, so the results are in-sample and
best read as an optimistic upper bound. **Not investment advice.** Past performance
is not indicative of future results.
