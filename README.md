# nifty-institutional-bot

Zero‑dependency, thread‑safe, memory‑efficient trading signal board for NIFTY 50, NIFTY BANK, and SENSEX.  
Designed for resource‑constrained environments (Render Free Tier, Termux, Pydroid 3).

## Core Features
- Multi‑layered structural analysis (Clone Completion, Origin Mapping, Liquidity Sweeps).
- 100-Point Weighted Decision Matrix.
- Volatility-based adaptive polling (1s/5s/10s intervals).
- 5-Minute Pre-Alert before 15‑min candle close.
- SQLite WAL mode storage with 120-day automated pruning.
- Supervisor Watchdog for automatic thread recovery.

## Quick Start
```bash
python main.py
