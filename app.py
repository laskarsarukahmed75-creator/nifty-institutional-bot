import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#!/usr/bin/env python3
# ============================================================================
# START MODULE: App
# Version: 1.0.0
# Dependencies: core.main_engine
# Public Functions: main
# Upgrade Notes: Only entry point. Replace with different runner if needed.
# ============================================================================

from core.main_engine import MainEngine

def main():
    engine = MainEngine()
    engine.start()

if __name__ == "__main__":
    main()

# ============================================================================
# END MODULE: App
# ============================================================================
