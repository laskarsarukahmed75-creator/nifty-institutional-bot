#!/bin/bash
# render-build.sh – Force-clean install with system dependencies

set -e  # exit on any error

echo "=== Installing system dependencies ==="
apt-get update -y
apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    python3-dev
rm -rf /var/lib/apt/lists/*

echo "=== Upgrading pip and installing Python packages ==="
pip install --upgrade pip
pip install --no-cache-dir --force-reinstall -r requirements.txt

echo "=== Verifying critical imports ==="
python -c "import smartapi; print('✅ smartapi imported successfully')"
python -c "from smartapi import SmartConnect; print('✅ SmartConnect imported')"

echo "=== Build completed successfully ==="
