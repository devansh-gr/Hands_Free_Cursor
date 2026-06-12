#!/bin/zsh
# Launch the AirPods IMU bridge.
#
# Must go through `open` (launchd) rather than direct exec: TCC attributes
# privacy access to the responsible process, which for a direct exec is the
# hosting terminal app (Terminal/VS Code) — none of which carry
# NSMotionUsageDescription, so CoreMotion SIGABRTs. Via `open`, the bundle is
# its own responsible process and its Info.plist is honored.
set -euo pipefail
cd "$(dirname "$0")/bridge"
[ -x .build/TelekinesisBridge.app/Contents/MacOS/bridge ] || ./package_app.sh

APP="$PWD/.build/TelekinesisBridge.app"
LOG=/tmp/telekinesis_bridge.log
: > "$LOG"

cleanup() { pkill -f "TelekinesisBridge.app" 2>/dev/null || true; }
trap 'cleanup; exit 0' INT TERM

open -n -a "$APP" --stdout "$LOG" --stderr "$LOG"
echo "bridge launched via launchd — ctrl-c here stops it. log follows:"
tail -F "$LOG"
