#!/bin/zsh
# Assemble the bridge into a minimal .app bundle. Required: macOS 26 TCC only
# honors NSMotionUsageDescription from a real bundle's Info.plist — a plist
# embedded in a bare CLI binary gets ignored and the process is SIGABRT'd.
set -euo pipefail
cd "$(dirname "$0")"

swift build -c release

APP=".build/TelekinesisBridge.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp Resources/BundleInfo.plist "$APP/Contents/Info.plist"
cp .build/release/bridge "$APP/Contents/MacOS/bridge"
codesign --force --sign - "$APP"

echo "packaged: $PWD/$APP"
echo "run with: \"$PWD/$APP/Contents/MacOS/bridge\""
