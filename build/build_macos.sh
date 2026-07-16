#!/bin/bash
# Build a portable Munshi distribution on macOS.
# Output: build/dist/Munshi/  (drop on a USB or zip and email)
#
# Run from the project root:
#   bash build/build_macos.sh

set -e

ROOT="$(cd "$(dirname "$0")/.."; pwd)"
cd "$ROOT"

# Python to use. CI sets PY=python (the workflow's set-up Python, which has the
# deps installed); locally it defaults to the system python3.
PY="${PY:-/usr/bin/python3}"

echo "════════════════════════════════════════════════════════════"
echo "  Building Munshi for macOS"
echo "════════════════════════════════════════════════════════════"
echo "  Working directory: $ROOT"

# Ensure deps are present
echo ""
echo "─ Verifying build dependencies"
"$PY" -m pip show pyinstaller >/dev/null 2>&1 || {
  echo "  Installing PyInstaller..."
  "$PY" -m pip install --user --quiet pyinstaller
}

# Clean previous builds (in build/ so we don't dirty the source tree)
echo ""
echo "─ Cleaning previous build artifacts"
rm -rf build/dist build/work
mkdir -p build/dist build/work

# Run PyInstaller
echo ""
echo "─ Running PyInstaller (this takes ~30-60 sec)"
"$PY" -m PyInstaller \
  --noconfirm \
  --distpath build/dist \
  --workpath build/work \
  build/munshi.spec

# Drop the customer-facing launcher script + first-run README inside the bundle
DIST="build/dist/Munshi"
echo ""
echo "─ Adding launcher script + README to $DIST"

cat > "$DIST/Run Munshi.command" <<'LAUNCHER'
#!/bin/bash
# Double-click this file to launch Munshi.
# All data is stored in this folder — keep it safe.
cd "$(dirname "$0")"
./Munshi
LAUNCHER
chmod +x "$DIST/Run Munshi.command"

cat > "$DIST/README — start here.txt" <<'README'
Munshi — Your Trucks' Digital Ledger Keeper
═══════════════════════════════════════════

How to start the app:
  • macOS:   Double-click "Run Munshi.command"
  • Windows: Double-click "Munshi.exe"

What happens:
  • A terminal window opens and stays open while Munshi is running
  • Your browser opens automatically at http://127.0.0.1:5056
  • Sign in (first time = username "Owner" / password "Owner",
    you'll be asked to change it immediately)
  • Don't close the terminal — that stops Munshi

Where your data lives:
  • bills.db                    Your ledger, bills, challans, etc.
  • backups/bills-YYYY-MM-DD.db Automatic daily backups
  • uploads/                    Photos of PoDs, challans, ledger pages

YOUR DATA NEVER LEAVES THIS FOLDER. We never see it.
If you set up Google Drive backup (Settings → Google Drive Backup),
the daily backup file is also copied to a folder in YOUR OWN Drive.

Need help? Contact: <support details TBD>
README

# Print summary
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Build complete"
echo "════════════════════════════════════════════════════════════"
SIZE=$(/usr/bin/du -sh "$DIST" 2>/dev/null | awk '{print $1}')
echo "  Bundle: $DIST"
echo "  Size:   $SIZE"
echo ""
echo "  To test, run:"
echo "    cd \"$DIST\""
echo "    ./Munshi          (or open 'Run Munshi.command')"
echo ""
echo "  To distribute, zip the entire $DIST/ folder and copy to a USB."
echo "════════════════════════════════════════════════════════════"
