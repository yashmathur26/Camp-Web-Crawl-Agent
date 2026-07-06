#!/usr/bin/env bash
# Set up Google Drive for Desktop to sync this project's docs/ folder for FRAIM doc sharing.
# Run after installing Google Drive and signing in with your Google account.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS_DIR="$PROJECT_ROOT/docs"
PROJECT_NAME="Camp-Web-Crawl-Agent"

if [[ ! -d "$DOCS_DIR" ]]; then
  echo "Error: docs folder not found at $DOCS_DIR" >&2
  exit 1
fi

if [[ ! -d "/Applications/Google Drive.app" ]]; then
  echo "Google Drive for Desktop is not installed."
  echo "Install from: https://www.google.com/drive/download/"
  exit 1
fi

echo "Project docs folder: $DOCS_DIR"
echo ""

# Find the signed-in Google Drive mount (stream mode on macOS).
DRIVE_MOUNT=""
for candidate in "$HOME/Library/CloudStorage"/GoogleDrive-*; do
  if [[ -d "$candidate/My Drive" ]]; then
    DRIVE_MOUNT="$candidate/My Drive"
    break
  fi
done

if [[ -n "$DRIVE_MOUNT" ]]; then
  LINK="$DRIVE_MOUNT/${PROJECT_NAME}-docs"
  if [[ ! -e "$LINK" ]]; then
    ln -s "$DOCS_DIR" "$LINK"
    echo "Created Finder shortcut: $LINK"
  else
    echo "Finder shortcut already exists: $LINK"
  fi
  echo ""
fi

echo "Enable cloud sync for doc sharing (one-time, keeps files in the repo):"
echo "  1. Click the Google Drive icon in the menu bar"
echo "  2. Open Settings (gear) → Preferences"
echo "  3. Go to My Computer → Add folder"
echo "  4. Select: $DOCS_DIR"
echo "  5. Choose 'Sync with Google Drive' (keeps files in place)"
echo ""
echo "Opening Google Drive…"
open -a "Google Drive" 2>/dev/null || true

echo ""
echo "After sync is active, confirm at https://drive.google.com under Computers → this Mac."
echo ""
echo "FRAIM doc review workflow:"
echo "  - FRAIM writes .docx/.md artifacts under docs/"
echo "  - Open files in Google Docs from drive.google.com (right-click → Open with)"
echo "  - Add comments, save — changes sync back to the repo automatically"
