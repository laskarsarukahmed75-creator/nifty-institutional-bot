# Nifty Institutional Bot – Signal Board

## Overview
A production‑grade signal intelligence platform that analyses Nifty and Bank Nifty using advanced market structure theories (Clone, Accumulation/Distribution, Liquidity, CHOCH, BOS). Generates 0–2 high‑confidence signals per day.

## Features
- Multi‑source data (Yahoo → Stooq → TwelveData → Cache)
- 10‑layer signal validation pipeline
- Dynamic confidence scoring (0–100)
- Continuous health & validator monitoring
- Watchdog with heartbeat for thread recovery
- Aggregated storage (raw → 1min → 5min → auto‑delete)
- Lightweight dashboard with engine health
- Render Free Tier compatible

## Deployment on Render
1. Push to GitHub.
2. Create Web Service on Render.
3. Set environment variables (PORT, DB_PATH, TWELVE_API_KEY optional).
4. Build: `pip install -r requirements.txt`
5. Start: `python main.py`

## Dashboard
Access your Render URL to see live signals and health status.
API endpoints: `/api/signal`, `/api/structure`, `/api/health`
