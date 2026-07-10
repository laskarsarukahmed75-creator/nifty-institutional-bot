#!/usr/bin/env python3
"""
error_filter.py – Lightweight Startup Diagnostic for Nifty Institutional Bot
Detects and explains the original startup error with recommended fixes.
Includes timeout on engine instantiation and top‑level crash protection.
"""

import os
import sys
import subprocess
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

REQUIRED_IMPORTS = [
    "SmartApi",
    "requests",
    "flask",
    "gunicorn",
    "sqlite3",
    "threading"
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


# ---- Diagnostic functions (each returns (status, details, recommended_fix) ----
def check_environment_variables() -> tuple:
    """Check required environment variables."""
    issues = []
    fixes = []
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            issues.append(f"Missing environment variable: {var}")
            fixes.append(f"Set {var} in Render Dashboard Environment Variables or in a .env file.")
    if issues:
        return "FAIL", "\n".join(issues), "\n".join(fixes)
    return "OK", "All required environment variables are set.", ""

def check_requirements() -> tuple:
    """Check if requirements.txt packages are installed."""
    if not os.path.exists(REQUIREMENTS_FILE):
        return "FAIL", "requirements.txt not found.", "Create requirements.txt with required packages."
    issues = []
    fixes = []
    try:
        with open(REQUIREMENTS_FILE, "r") as f:
            required = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        # Use importlib.metadata if available, else pkg_resources
        try:
            from importlib.metadata import distribution, PackageNotFoundError
        except ImportError:
            from pkg_resources import get_distribution, DistributionNotFound as PackageNotFoundError
            distribution = get_distribution
        for req in required:
            try:
                pkg_name = req.split("==")[0] if "==" in req else req.split(">=")[0] if ">=" in req else req
                dist = distribution(pkg_name)
            except PackageNotFoundError:
                issues.append(f"Package not installed: {req}")
                fixes.append(f"Run: pip install {req}")
    except Exception as e:
        issues.append(f"Error reading requirements.txt: {e}")
        fixes.append("Check file permissions and syntax.")
    if issues:
        return "FAIL", "\n".join(issues), "\n".join(fixes)
    return "OK", "All packages installed.", ""

def check_imports() -> tuple:
    """Try to import required modules and capture full traceback."""
    results = []
    fixes = []
    for mod_name in REQUIRED_IMPORTS:
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

def check_database() -> tuple:
    """Check if SQLite database is accessible."""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        conn.execute("SELECT 1")
        conn.close()
        return "OK", "Database accessible.", ""
    except Exception as e:
        return "FAIL", f"Database error: {e}", "Ensure the directory is writable and the DB file is not locked."

def check_engine_import() -> tuple:
    """
    Import the NiftyInstitutionalEngine class from app.py and capture any exception.
    """
    try:
        import app
        if hasattr(app, "NiftyInstitutionalEngine"):
            return "OK", "NiftyInstitutionalEngine class imported successfully.", ""
        else:
            return "FAIL", "Class NiftyInstitutionalEngine not found in app.py", "Check that app.py contains the class definition."
    except Exception as e:
        tb = traceback.format_exc()
        return "FAIL", f"Import error: {e}\nTraceback:\n{tb}", "Fix syntax errors in app.py or ensure all dependencies are installed."

def run_engine_instantiation_with_timeout() -> tuple:
    """
    Attempt to instantiate the engine with a timeout.
    Returns (status, details, recommended_fix)
    """
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
        result["fix"] = "Check if any external API call is hanging (e.g., login). Ensure network connectivity and credentials are valid."
        # Optionally, we could try to kill the thread, but that's unsafe; we just report.
    return result["status"], result["details"], result["fix"]


# ---- Main diagnostic runner with top‑level protection ----
def run_diagnostics():
    print_info("Running startup diagnostics for Nifty Institutional Bot...")

    # Ensure we always produce a report even if something unexpected happens.
    try:
        # Build the report dictionary.
        report = {}
        report["Environment Variables"] = "{} - {}".format(*check_environment_variables())
        report["Requirements"] = "{} - {}".format(*check_requirements())
        import_status, import_details, import_fix = check_imports()
        report["Imports"] = f"{import_status} - {import_details}\n    Fix: {import_fix}" if import_fix else f"{import_status} - {import_details}"

        db_status, db_details, db_fix = check_database()
        report["Database"] = f"{db_status} - {db_details}\n    Fix: {db_fix}" if db_fix else f"{db_status} - {db_details}"

        eng_import_status, eng_import_details, eng_import_fix = check_engine_import()
        report["Engine Import"] = f"{eng_import_status} - {eng_import_details}\n    Fix: {eng_import_fix}" if eng_import_fix else f"{eng_import_status} - {eng_import_details}"

        # Only try instantiation if engine import succeeded, else skip.
        if eng_import_status == "OK":
            inst_status, inst_details, inst_fix = run_engine_instantiation_with_timeout()
            report["Engine Instantiation"] = f"{inst_status} - {inst_details}\n    Fix: {inst_fix}" if inst_fix else f"{inst_status} - {inst_details}"
        else:
            report["Engine Instantiation"] = "⏩ Skipped (engine import failed)"

        # Print final summary
        print_report(report)

        # Decide exit code
        if any("FAIL" in str(v) or "TIMEOUT" in str(v) for v in report.values()):
            print_error("One or more critical issues found. Please fix them before starting the bot.")
            return False
        else:
            print_success("All diagnostics passed. The bot should start correctly.")
            return True

    except Exception as e:
        # Top-level catch to prevent the filter from crashing.
        tb = traceback.format_exc()
        print_error("Unexpected error in diagnostic filter itself:")
        print(f"Error: {e}")
        print(f"Traceback:\n{tb}")
        print("Please report this issue.")
        return False


if __name__ == "__main__":
    success = run_diagnostics()
    sys.exit(0 if success else 1)
