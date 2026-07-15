# nifty-institutional-bot – Institutional Grade Signal Board

**Ultimate version** – combines the full original feature set with ATR‑weighted breakout, institutional OI skew mechanics, and advanced anti‑trap filters. Continuous data ingestion – never sleeps.

## Features
- Adaptive polling (1s default)
- Weighted scoring matrix (Clone, Origin, Liquidity, Structure, Trap, Premium)
- ATR‑weighted volume breakout and adaptive thresholds
- Institutional OI skew (PCR, Call/Put skew) and strike‑level barrier detection
- Multi‑zone anti‑trap filtering (reduces false signals)
- Pre‑alert 5 minutes before candle close
- Real‑time mock data fallback for continuous testing
- ASCII dashboard with support/resistance, entry, SL, TP
- SQLite storage with WAL and automated pruning (120‑day retention)
- Watchdog supervisor with auto‑restart (up to 5 attempts)
- Built‑in HTTP health check for Render

## Deploy on Render
- Set `FORCE_SESSION=true` to keep bot running 24/7.
- All configuration via environment variables (optional).

## Run Locally
```bash
python main.py
