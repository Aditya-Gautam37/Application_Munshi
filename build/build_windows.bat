@echo off
REM Build a portable Munshi distribution on Windows.
REM Output: build\dist\Munshi\  (drop on a USB or zip and email)
REM
REM Run from the project root:
REM   build\build_windows.bat
REM
REM Prerequisites:
REM   - Python 3.10+ installed
REM   - pip install -r requirements.txt run at least once
REM   - pip install pyinstaller

setlocal
set ROOT=%~dp0..
cd /d "%ROOT%"

echo ============================================================
echo   Building Munshi for Windows
echo ============================================================
echo   Working directory: %CD%

REM Check pyinstaller is installed
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo   Installing PyInstaller...
  python -m pip install --quiet pyinstaller
)

REM Clean previous builds
echo.
echo - Cleaning previous build artifacts
if exist build\dist  rmdir /s /q build\dist
if exist build\work  rmdir /s /q build\work
mkdir build\dist
mkdir build\work

REM Run PyInstaller
echo.
echo - Running PyInstaller (this takes ~60 sec)
python -m PyInstaller --noconfirm --distpath build\dist --workpath build\work build\munshi.spec
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

REM Drop the launcher batch + README
set DIST=build\dist\Munshi
echo.
echo - Adding launcher + README to %DIST%

> "%DIST%\Run Munshi.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo Munshi.exe
)

> "%DIST%\README - start here.txt" (
  echo Munshi - Your Trucks' Digital Ledger Keeper
  echo ===========================================
  echo.
  echo How to start the app:
  echo   - Windows: Double-click "Munshi.exe" or "Run Munshi.bat"
  echo.
  echo What happens:
  echo   - A terminal window opens and stays open while Munshi is running
  echo   - Your browser opens automatically at http://127.0.0.1:5056
  echo   - Sign in ^(first time = username "Owner" / password "Owner"^)
  echo   - Don't close the terminal - that stops Munshi
  echo.
  echo Where your data lives:
  echo   - bills.db                       Your ledger
  echo   - backups\bills-YYYY-MM-DD.db    Automatic daily backups
  echo   - uploads\                       Photos of PoDs, challans, etc.
  echo.
  echo YOUR DATA NEVER LEAVES THIS FOLDER. We never see it.
  echo If you set up Google Drive backup, the daily backup is also
  echo copied to a folder in YOUR OWN Drive.
)

echo.
echo ============================================================
echo   Build complete
echo ============================================================
echo   Bundle: %DIST%
echo.
echo   To test, run:
echo     cd "%DIST%"
echo     Munshi.exe
echo.
echo   To distribute, zip the entire %DIST%\ folder and copy to a USB.
echo ============================================================

endlocal
