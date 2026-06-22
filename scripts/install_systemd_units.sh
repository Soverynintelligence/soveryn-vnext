#!/usr/bin/env bash
# Idempotent install/uninstall of SOVERYN systemd user units.
#
# Usage:
#   ./install_systemd_units.sh --install
#   ./install_systemd_units.sh --uninstall
#   ./install_systemd_units.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_SYSTEMD_DIR="${SCRIPT_DIR}/../systemd"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"

UNITS=(
  soveryn-router.service
  soveryn-vnext.service
  soveryn-ares.service
  soveryn.target
  soveryn-cognition-instance.service
)

MODE="${1:-}"

copy_units() {
  mkdir -p "$USER_SYSTEMD_DIR"
  for unit in "${UNITS[@]}"; do
    src="${REPO_SYSTEMD_DIR}/${unit}"
    dst="${USER_SYSTEMD_DIR}/${unit}"
    [[ -f "$src" ]] || { echo "FATAL: missing $src" >&2; exit 1; }
    cp -v "$src" "$dst"
  done
}

remove_units() {
  for unit in "${UNITS[@]}"; do
    dst="${USER_SYSTEMD_DIR}/${unit}"
    if [[ -f "$dst" ]]; then
      rm -v "$dst"
    fi
  done
}

case "$MODE" in
  --install)
    copy_units
    systemctl --user daemon-reload
    echo
    echo "Installed. Next steps:"
    echo "  systemctl --user enable soveryn.target   # auto-start at login"
    echo "  systemctl --user start  soveryn.target   # start now"
    echo "  python -m soveryn.status                 # verify"
    ;;
  --uninstall)
    remove_units
    systemctl --user daemon-reload
    echo "Uninstalled. (Did NOT stop running units — do that manually if needed.)"
    ;;
  --dry-run)
    echo "Would copy these files from ${REPO_SYSTEMD_DIR} to ${USER_SYSTEMD_DIR}:"
    for unit in "${UNITS[@]}"; do
      echo "  ${unit}"
    done
    echo "Then: systemctl --user daemon-reload"
    ;;
  --help|-h|"")
    cat <<EOF
Usage: $0 [--install | --uninstall | --dry-run]

Idempotent management of SOVERYN systemd user units. No sudo needed —
units live under ~/.config/systemd/user/.

  --install    Copy units from repo to user-config, then daemon-reload.
               Re-running is safe (cp -v overwrites). Does NOT enable or
               start units — operator runs systemctl --user enable + start.
  --uninstall  Remove the four units + daemon-reload. Does NOT stop running
               units — operator stops them manually if needed.
  --dry-run    Print the planned actions without executing.
EOF
    [[ "${MODE}" == "--help" || "${MODE}" == "-h" ]] && exit 0
    exit 1
    ;;
  *)
    echo "Unknown mode: $MODE — use --help" >&2
    exit 1
    ;;
esac
