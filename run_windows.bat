@echo off
REM Developer launcher (requires Python 3.10+ installed).
REM Customers should use the bundled Munshi.exe instead.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python not found. Please install Python 3.10+ from https://python.org
  pause
  exit /b
)

python -c "import flask, dotenv, google.genai" >nul 2>&1
if errorlevel 1 (
  echo Installing/updating dependencies (one-time setup)...
  pip install -r requirements.txt --quiet --upgrade
)

echo Starting Munshi (Jainpur Logistic) on port 5056...
python app.py
