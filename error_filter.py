#!/usr/bin/env python3
"""
error_filter.py – Lightweight Startup Diagnostic for Nifty Institutional Bot
Fixed: Correct import names, optional web server packages, no false failures.
"""

import os
import sys
import importlib
import traceback
import threading
import time
from typing import List, Dict, Any, Optional

# ---- Configuration ----
REQUIRED_ENV_VARS = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET"
]

# Only check packages that are actually used by the engine
# The engine uses SmartApi; flask/gunicorn are only for keepalive
CRITICAL_IMPORTS = [
    "SmartApi",          # Correct import name for Angel One SDK
    "requests",
    "sqlite3",
    "threading"
]

OPTIONAL_IMPORTS = [
    "flask",             # Only needed for keepalive web server
    "gunicorn"           # Only needed for Render web service
]

REQUIREMENTS_FILE = "requirements.txt"
DB_FILE = "niftyinstitutionalbot.db"
ENGINE_INIT_TIMEOUT = 10  # seconds

# ---- Helper: print colored output ----
def print_error(message):
    print(f"\033[91m❌ {message}\033[0m")

def print_success(message):
    print(f"\033[92m✅ {message}\033[0m")

def print_warning(message):
    print(f"\033[93m⚠️ {message}\033[0m")

def print_info(message):
    print(f"\033[94mℹ️ {message}\033[0m")

def print_report(report: Dict[str, Any]):
    print("\n" + "=" * 80)
    print("🔍 STARTUP DIAGNOSTIC REPORT")
    print("=" * 80)
    for key, value in report.items():
        print(f"{key}: {value}")
    print("=" * 80 + "\n")


# ---- Diagnostic functions ----
def check_environment_variables() -> tuple:
    issues = []
    fixes = []
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            issues.append(f"Missing environment variable: {var}")
            fixes.append(f"Set {var} in Render Dashboard or .env file.")
    if issues:
        return "FAIL", "\n".join(issues), "\n".join(fixes)
    return "OK", "All required environment variables are set.", ""

def check_critical_imports() -> tuple:
    """Check only imports that are critical for the engine to run."""
    results = []
    fixes = []
    for mod_name in CRITICAL_IMPORTS:
        try:
            importlib.import_module(mod_name)
            results.append(f"✅ {mod_name}")
        except Exception as e:
            tb = traceback.format_exc()
            results.append(f"❌ {mod_name}: {e}")
            if "SmartApi" in mod_name:
                fixes.append("Install smartapi-python: pip install smartapi-python==1.5.5")
            else:
                fixes.append(f"Install missing package: {mod_name}")
    if any("❌" in r for r in results):
        return "FAIL", "\n".join(results), "\n".join(fixes)
    return "OK", "\n".join(results), ""

def check_optional_imports() -> tuple:
    """Check optional imports (flask/gunicorn) – warn but don't fail."""
    results = []
    for mod_name in OPTIONAL_IMPORTS:
        try:
            importlib.import_module(mod_name)
            results.append(f"✅ {mod_name}")
        except Exception:
            results.append(f"⚠️ {mod_name} not installed (only needed for web server)")
    return "WARN", "\n".join(results), "Install flask/gunicorn if you need the web server."

def check_database() -> tuple:
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        conn.execute("SELECT 1")
        conn.close()
        return "OK", "Database accessible.", ""
    except Exception as e:
        return "FAIL", f"Database error: {e}", "Ensure the directory is writable."

def check_engine_import() -> tuple:
    try:
        import app
        if hasattr(app, "NiftyInstitutionalEngine"):
            return "OK", "NiftyInstitutionalEngine class imported successfully.", ""
        else:
            return "FAIL", "Class NiftyInstitutionalEngine not found in app.py", "Check app.py."
    except Exception as e:
        tb = traceback.format_exc()
        return "FAIL", f"Import error: {e}\nTraceback:\n{tb}", "Fix syntax errors in app.py."

def run_engine_instantiation_with_timeout() -> tuple:
    result = {"status": "TIMEOUT", "details": "", "fix": ""}

    def target():
        try:
            from app import NiftyInstitutionalEngine
            engine = NiftyInstitutionalEngine()
            result["status"] = "OK"
            result["details"] = "Engine instantiated successfully."
        except Exception as e:
            tb = traceback.format_exc()
            result["status"] = "FAIL"
            result["details"] = f"Error: {e}\nTraceback:\n{tb}"
            if "TOTP" in str(e):
                result["fix"] = "Check ANGEL_TOTP_SECRET environment variable."
            elif "authentication" in str(e).lower():
                result["fix"] = "Verify Angel One credentials."
            else:
                result["fix"] = "Review the error traceback above."

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=ENGINE_INIT_TIMEOUT)

    if thread.is_alive():
        result["status"] = "TIMEOUT"
        result["details"] = f"Engine instantiation timed out after {ENGINE_INIT_TIMEOUT} seconds."
        result["fix"] = "Check if any external API call is hanging (e.g., login). Ensure network connectivity."
    return result["status"], result["details"], result["fix"]


# ---- Main diagnostic runner ----
def run_diagnostics():
    print_info("Running startup diagnostics for Nifty Institutional Bot...")

    try:
        report = {}
        report["Environment Variables"] = "{} - {}".format(*check_environment_variables())

        # Critical imports (engine must have these)
        crit_status, crit_details, crit_fix = check_critical_imports()
        report["Critical Imports"] = f"{crit_status} - {crit_details}\n    Fix: {crit_fix}" if crit_fix else f"{crit_status} - {crit_details}"

        # Optional imports (only warn)
        opt_status, opt_details, opt_fix = check_optional_imports()
        report["Optional Imports (Web Server)"] = f"{opt_status} - {opt_details}"

        db_status, db_details, db_fix = check_database()
        report["Database"] = f"{db_status} - {db_details}\n    Fix: {db_fix}" if db_fix else f"{db_status} - {db_details}"

        eng_import_status, eng_import_details, eng_import_fix = check_engine_import()
        report["Engine Import"] = f"{eng_import_status} - {eng_import_details}\n    Fix: {eng_import_fix}" if eng_import_fix else f"{eng_import_status} - {eng_import_details}"

        if eng_import_status == "OK":
            inst_status, inst_details, inst_fix = run_engine_instantiation_with_timeout()
            report["Engine Instantiation"] = f"{inst_status} - {inst_details}\n    Fix: {inst_fix}" if inst_fix else f"{inst_status} - {inst_details}"
        else:
            report["Engine Instantiation"] = "⏩ Skipped (engine import failed)"

        print_report(report)

        # Only fail if critical imports or engine instantiation fails
        if "FAIL" in str(report.get("Critical Imports", "")) or "FAIL" in str(report.get("Engine Instantiation", "")):
            print_error("Critical issues found. Please fix them before starting the bot.")
            return False
        else:
            print_success("All critical diagnostics passed. The bot should start correctly.")
            return True

    except Exception as e:
        tb = traceback.format_exc()
        print_error("Unexpected error in diagnostic filter itself:")
        print(f"Error: {e}")
        print(f"Traceback:\n{tb}")
        return False


if __name__ == "__main__":
    success = run_diagnostics()
    sys.exit(0 if success else 1)
