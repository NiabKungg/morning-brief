#!/bin/bash
# key-exchange.sh — สลับ SSH key กับอีกเครื่อง (รันบนทั้งสองเครื่อง สลับ argument)
# ใช้: bash key-exchange.sh <user> <host>   เช่น  bash key-exchange.sh pi5 raspberrypi.local
set -eu
USER_T="${1:?ใส่ user เป้าหมาย}"
HOST_T="${2:?ใส่ host เป้าหมาย}"
KEY="$HOME/.ssh/id_ed25519"

mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -f "$KEY" -q
ssh-copy-id -o StrictHostKeyChecking=accept-new "$USER_T@$HOST_T"
ssh -o ConnectTimeout=8 "$USER_T@$HOST_T" 'echo "key OK ✓"'
