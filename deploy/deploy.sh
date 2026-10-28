#!/usr/bin/env bash
# Deploy MIB from this checkout to the Pis: code (rsync), Python deps (uv sync --frozen), systemd units, restart.
# Usage: deploy/deploy.sh [all|pi5|pi4]     Hosts default to the ssh aliases pi5 / pi4 (override PI5=… PI4=…).
# First run creates ~/mib/hub.env (random worker token) on the Pi 5 and ~/mib/worker.env on the Pi 4.
# sudo on the Pis asks for the password once per host (units + restart).
set -euo pipefail
cd "$(dirname "$0")/.."

PI5=${PI5:-pi5}
PI4=${PI4:-pi4}
EXCLUDES=(--exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude '*.pyc' --exclude tests)

remote() { ssh "$1" "bash -lc $(printf %q "$2")"; }
remote_sudo() { ssh -t "$1" "sudo bash -c $(printf %q "$2")"; }
sync_code() {
  remote "$1" 'mkdir -p ~/mib/app ~/mib/data'
  # No -z: macOS's openrsync can stall against GNU rsync with compression on; the tree is ~2 MB anyway.
  rsync -a --delete "${EXCLUDES[@]}" ./ "$1:mib/app/"
}
uv_sync() { remote "$1" "cd ~/mib/app && UV_PYTHON_PREFERENCE=only-system ~/.local/bin/uv sync --frozen --no-dev --extra $2 -q"; }

deploy_pi5() {
  echo "==> $PI5 (hub + llama-server)"
  sync_code "$PI5"
  remote "$PI5" 'test -f ~/mib/hub.env || (umask 077; sed "s/^MIB_TOKEN=.*/MIB_TOKEN=$(openssl rand -hex 24)/" \
    ~/mib/app/deploy/pi5/hub.env.example > ~/mib/hub.env)'
  uv_sync "$PI5" hub
  # Restart llama-server only when its unit (flags) changed: reloading the model costs a few seconds.
  remote_sudo "$PI5" 'u=/etc/systemd/system/mib-llm.service; new=/home/pi5/mib/app/deploy/pi5/mib-llm.service; \
    if cmp -s "$new" "$u"; then llm=start; else llm=restart; fi; \
    install -m 644 "$new" /home/pi5/mib/app/deploy/pi5/mib-hub.service /etc/systemd/system/ \
    && systemctl daemon-reload && systemctl enable -q mib-llm mib-hub && systemctl $llm mib-llm \
    && systemctl restart mib-hub && systemctl is-active mib-llm mib-hub'
}

deploy_pi4() {
  echo "==> $PI4 (worker)"
  local token hub_host
  token=$(remote "$PI5" 'grep "^MIB_TOKEN=" ~/mib/hub.env | cut -d= -f2')
  # The Pi 5 by mDNS name, not IP: the address changes whenever DHCP does (e.g. a phone hotspot carrying the home
  # Wi-Fi's name); <hostname>.local follows the Pi.
  hub_host="$(remote "$PI5" hostname).local"
  sync_code "$PI4"
  remote "$PI4" "getent hosts $hub_host >/dev/null \
    || echo 'warning: $PI4 cannot resolve $hub_host (needs avahi-daemon on the Pi 5, libnss-mdns on the Pi 4)' >&2"
  remote "$PI4" "test -f ~/mib/worker.env || (umask 077; sed -e 's|^MIB_TOKEN=.*|MIB_TOKEN=$token|' \
    -e 's|^MIB_HUB_WS=.*|MIB_HUB_WS=ws://$hub_host:8800/ws/worker|' ~/mib/app/deploy/pi4/worker.env.example > ~/mib/worker.env)"
  uv_sync "$PI4" worker
  remote_sudo "$PI4" 'install -m 644 /home/pi4/mib/app/deploy/pi4/mib-worker.service /etc/systemd/system/ \
    && systemctl daemon-reload && systemctl enable -q mib-worker && systemctl restart mib-worker \
    && systemctl is-active mib-worker'
}

case "${1:-all}" in
  all) deploy_pi5; deploy_pi4 ;;
  pi5) deploy_pi5 ;;
  pi4) deploy_pi4 ;;
  *) echo "usage: $0 [all|pi5|pi4]" >&2; exit 2 ;;
esac
echo "==> done: http://$(remote "$PI5" hostname).local:8800"
