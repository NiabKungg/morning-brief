#!/bin/bash
# run.sh — คำสั่งเดียวจบ: กวาดข้อมูล แล้ว push ไป Pi 5
set -u
BASE="$(cd "$(dirname "$0")" && pwd)"
"$BASE/.venv/bin/python" "$BASE/collector.py"
rc=$?
bash "$BASE/push.sh"
push_rc=$?
exit $(( rc > 0 ? rc : push_rc ))
