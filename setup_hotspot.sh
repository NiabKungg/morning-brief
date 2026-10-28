#!/bin/bash
# setup_hotspot.sh — เพิ่ม WiFi hotspot หน้างานให้เครื่องนี้ (ใช้ก่อนวันพรีเซนต์)
# ใช้: sudo ./setup_hotspot.sh "ชื่อSSID" "รหัสผ่าน"
# ระบบจะจำ network นี้ไว้ auto-connect เองเมื่อเห็น SSID นี้ (priority สูงกว่าเดิม)
set -eu
SSID="${1:?ใส่ชื่อ SSID}"
PASS="${2:?ใส่รหัสผ่าน}"
DEV="${3:-wlan0}"
NAME="hotspot-$SSID"

nmcli connection add type wifi ifname "$DEV" con-name "$NAME" ssid "$SSID" \
    -- wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
    connection.autoconnect yes connection.autoconnect-priority 20
echo "เพิ่ม $NAME แล้ว — ทดสอบเชื่อมต่อเลยไหม? (yes/no)"
read -r ans
[ "$ans" = "yes" ] && nmcli connection up "$NAME"
echo "เสร็จ ตรวจสอบด้วย: nmcli device status && hostname -I"
