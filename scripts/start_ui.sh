#!/usr/bin/env bash
# Install and (re)start the knowledgebase UI as a systemd user service. It restarts
# after a crash and starts at boot (needs `loginctl enable-linger`, once).
#
#   scripts/start_ui.sh                          # http://127.0.0.1:8000, db/atlas_final.db
#   UI_HOST=0.0.0.0 UI_PORT=9000 scripts/start_ui.sh
#   UI_DB=db/atlas_dev.db scripts/start_ui.sh
#
# Status:  systemctl --user status mirna-ui
# Logs:    journalctl --user -u mirna-ui -f
# Stop:    systemctl --user disable --now mirna-ui
set -euo pipefail

SERVICE="mirna-ui"
UI_HOST="${UI_HOST:-127.0.0.1}"
UI_PORT="${UI_PORT:-8000}"
UI_DB="${UI_DB:-db/atlas_final.db}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

# ExecStartPost reads the database once in the background, so that its pages are in
# the OS file cache: uncached NFS reads make first page loads take seconds. Linux
# drops these pages again when other programs need the memory.
# No start limit: at boot, the NFS mount may not be there yet.
cat > "$UNIT_DIR/$SERVICE.service" <<EOF
[Unit]
Description=miRNA knowledgebase UI
StartLimitIntervalSec=0

[Service]
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python scripts/web/run_ui.py --host $UI_HOST --port $UI_PORT --db $UI_DB
ExecStartPost=-/bin/sh -c 'cat $UI_DB > /dev/null 2>&1 &'
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE" 2> /dev/null
systemctl --user restart "$SERVICE"

echo "UI starting as service '$SERVICE' at http://$UI_HOST:$UI_PORT"
