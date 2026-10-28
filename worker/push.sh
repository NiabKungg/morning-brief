#!/bin/bash
# push.sh — ส่งข้อมูลที่กวาดได้จาก Pi 4 ไปเก็บที่ Pi 5 ผ่าน rsync/SSH
# หา Pi 5 แบบไม่พึ่ง IP ตายตัว (เผื่อยกไปเสียบ hotspot หน้างาน):
#   1) mDNS  raspberrypi.local      (ใช้ได้เมื่ออยู่ LAN/hotspot เดียวกัน)
#   2) cached IP ไฟล์ state/pi5_ip  (จำ IP ล่าสุดที่เคยสำเร็จ)
#   3) ผ่าน Cloudflare tunnel        (ใช้ได้ทุกเครือข่าย ต้องมี cloudflared บนเครื่องนี้)
set -u
BASE="$(cd "$(dirname "$0")" && pwd)"
STATE="$BASE/state"
TARGET_USER="pi5"
CACHED_IP=""
[ -f "$STATE/pi5_ip" ] && CACHED_IP="$(cat "$STATE/pi5_ip")"

resolve_target() {
    if getent hosts raspberrypi.local >/dev/null 2>&1; then
        echo "raspberrypi.local"; return 0
    fi
    if [ -n "$CACHED_IP" ] && ping -c1 -W2 "$CACHED_IP" >/dev/null 2>&1; then
        echo "$CACHED_IP"; return 0
    fi
    if command -v cloudflared >/dev/null 2>&1; then
        echo "pi5.niabdev.xyz"; return 0
    fi
    return 1
}

ssh_opts() {
    local t="$1"
    if [ "$t" = "pi5.niabdev.xyz" ] && command -v cloudflared >/dev/null 2>&1; then
        echo "-o ProxyCommand=cloudflared\ access\ ssh\ --hostname\ pi5.niabdev.xyz -o StrictHostKeyChecking=accept-new"
    else
        echo "-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new"
    fi
}

TARGET="$(resolve_target)" || { echo "[push] FATAL: หา Pi 5 ไม่เจอ (mDNS/cache/tunnel)"; exit 1; }
echo "[push] target = $TARGET"

SSH_OPTS="$(ssh_opts "$TARGET")"
if rsync -az -e "ssh $SSH_OPTS" "$BASE/data/" "$TARGET_USER@$TARGET:morning-brief/incoming/"; then
    mkdir -p "$STATE"
    # จำ IP ล่าสุดที่ใช้สำเร็จ (ไม่ใช่ hostname) เผื่อรอบหน้า mDNS พัง
    IP="$(getent hosts "$TARGET" | awk '{print $1}' | head -1)"
    [ -n "$IP" ] && echo "$IP" > "$STATE/pi5_ip"
    echo "[push] OK -> $TARGET"
else
    # ลองเปลี่ยนเส้นทางสำรองอัตโนมัติหนึ่งรอบ
    echo "[push] primary failed, trying fallback..."
    if [ "$TARGET" != "pi5.niabdev.xyz" ] && command -v cloudflared >/dev/null 2>&1; then
        rsync -az -e "ssh -o ProxyCommand=cloudflared\ access\ ssh\ --hostname\ pi5.niabdev.xyz -o StrictHostKeyChecking=accept-new" \
            "$BASE/data/" "$TARGET_USER@pi5.niabdev.xyz:morning-brief/incoming/" \
            && { echo "[push] OK via tunnel"; exit 0; }
    fi
    echo "[push] FATAL: ส่งข้อมูลไม่สำเร็จทุกเส้นทาง"
    exit 1
fi
