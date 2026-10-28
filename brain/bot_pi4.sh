#!/bin/bash
# bot_pi4.sh — ติดต่อ Pi 4 จาก Pi 5 แบบไม่พึ่ง IP ตายตัว (เผื่อยกไปเสียบ hotspot)
# ใช้: bot_pi4.sh sweep      → สั่ง Pi 4 กวาดข้อมูลใหม่แล้ว push กลับมา
#      bot_pi4.sh sweepstatus → ดูว่า Pi 4 กวาดล่าสุดเมื่อไหร่
# ลำดับหา Pi 4: mDNS (pi4.local) → cached IP → Cloudflare tunnel
set -u
STATE="/home/pi5/morning-brief/state"
CACHED_IP=""
[ -f "$STATE/pi4_ip" ] && CACHED_IP="$(cat "$STATE/pi4_ip")"

resolve_pi4() {
    if getent hosts pi4.local >/dev/null 2>&1; then
        echo "pi4.local"; return 0
    fi
    if [ -n "$CACHED_IP" ] && ping -c1 -W2 "$CACHED_IP" >/dev/null 2>&1; then
        echo "$CACHED_IP"; return 0
    fi
    if command -v cloudflared >/dev/null 2>&1; then
        echo "pi4.niabdev.xyz"; return 0
    fi
    return 1
}

TUNNEL_SSH="ssh -o ProxyCommand=cloudflared\ access\ ssh\ --hostname\ pi4.niabdev.xyz -o StrictHostKeyChecking=accept-new"
DIRECT_SSH="ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new"

cmd="${1:-sweepstatus}"
TARGET="$(resolve_pi4)" || { echo "หา Pi 4 ไม่เจอ (mDNS/cache/tunnel)"; exit 1; }
echo "target=$TARGET" >&2

if [ "$TARGET" = "pi4.niabdev.xyz" ]; then
    SSH_CMD="$TUNNEL_SSH"
else
    SSH_CMD="$DIRECT_SSH"
fi

case "$cmd" in
    sweep)
        $SSH_CMD "pi4@$TARGET" "/home/pi4/morning-brief/run.sh" \
            && { IP="$(getent hosts "$TARGET" | awk '{print $1}' | head -1)"; \
                 mkdir -p "$STATE"; [ -n "$IP" ] && echo "$IP" > "$STATE/pi4_ip"; exit 0; }
        # primary พัง ลองเส้น tunnel สำรอง
        $TUNNEL_SSH "pi4@pi4.niabdev.xyz" "/home/pi4/morning-brief/run.sh"
        ;;
    sweepstatus)
        $SSH_CMD "pi4@$TARGET" "cat /home/pi4/morning-brief/state/last_sweep.txt 2>/dev/null || echo ยังไม่เคยกวาด"
        ;;
    *)
        echo "usage: $0 {sweep|sweepstatus}"; exit 2
        ;;
esac
