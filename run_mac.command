#!/bin/bash
# Developer launcher on Mac (requires Python 3.10+).
# Customers should use the bundled Munshi app instead.
cd "$(dirname "$0")"

if ! python3 -c "import flask, dotenv, google.genai" 2>/dev/null; then
  echo "Installing/updating dependencies (one-time setup)..."
  pip3 install -r requirements.txt --quiet --upgrade
fi

echo "Starting Munshi (Jainpur Logistic) on port 5056..."
python3 app.py
