# ☀️ Morning Intelligence Brief

ระบบ AI Agent ทำงานอัตโนมัติ 24/7 — กวาดข้อมูลข่าว/ตลาด/trending ทั้งคืน
ด้วย Raspberry Pi 4 แล้วสรุปเป็น Executive Summary ภาษาไทยด้วยโมเดลท้องถิ่น
(Gemma 4 e2b ผ่าน Ollama) ส่งเข้า Telegram ทุกเช้า 07:30 น.

โปรเจกต์ส่วนหนึ่งของรายวิชา 05506007 ระบบปฏิบัติการ — สาขาวิทยาการคอมพิวเตอร์ คณะวิทยาศาสตร์ สจล.

## สถาปัตยกรรม

```
[อินเทอร์เน็ต] RSS / CoinGecko / Stooq / GitHub API / Reddit
     │
┌───▼─────────────────────────┐   rsync ผ่าน SSH     ┌──────────────────────────────┐
│ Pi 4 — WORKER (2GB)         │  กวาดทุกชม. 22:00–07:00│ Pi 5 — BRAIN (8GB)           │
│ worker/                     │ ────────────────────▶ │ brain/                       │
│  fetch_rss.py               │  (หาเครื่องด้วย mDNS →  │  summarizer.py               │
│  fetch_market.py            │   cached IP → tunnel   │   → Ollama gemma4:e2b        │
│  fetch_github.py            │   ไม่พึ่ง IP ตายตัว!)   │  bot_listener.py (/now)      │
│  fetch_reddit.py            │                        │  systemd timer 07:05/07:40   │
│  collector.py + push.sh     │                        │  Telegram ส่ง 07:30          │
└─────────────────────────────┘                        └──────────────────────────────┘
```

## โครงสร้าง repo

```
worker/        # โค้ดบน Pi 4 — กวาดข้อมูล (fetcher 4 แหล่ง + collector + push)
brain/         # โค้ดบน Pi 5 — สรุปด้วย LLM + Telegram bot + timer
setup_hotspot.sh  # เพิ่ม WiFi hotspot หน้างาน (nmcli)
```

## ติดตั้งฝั่ง Worker (Pi 4)

```bash
sudo apt install -y python3-venv rsync avahi-utils
git clone https://github.com/NiabKungg/morning-brief.git ~/morning-brief
cd ~/morning-brief/worker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# สลับ SSH key กับ Pi 5 (ทั้งสองเครื่องรันหมด)
bash key-exchange.sh pi5 raspberrypi.local

# ติดตั้ง systemd units แล้วเปิดใช้
sudo cp systemd/* /etc/systemd/system/
sudo systemctl enable --now morning-brief-worker.timer
```

## ติดตั้งฝั่ง Brain (Pi 5)

```bash
# 1) Ollama — ดาวน์โหลดจาก https://ollama.com/download (Linux ARM64) แล้ว
sudo tar -C /usr -xf ollama-linux-arm64.tar.zst
sudo useradd -r -s /usr/sbin/nologin -m ollama || true
sudo cp ollama.service /etc/systemd/system/ && sudo systemctl enable --now ollama
ollama pull gemma4:e2b

# 2) โครงโปรเจกต์
git clone https://github.com/NiabKungg/morning-brief.git ~/morning-brief
cd ~/morning-brief/brain
cp config.env.example config.env && nano config.env   # ใส่ token + chat_id
chmod 600 config.env
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3) systemd
sudo cp systemd/* /etc/systemd/system/
sudo systemctl enable --now mb-bot.service morning-brief-brain.timer
```

## การใช้งานผ่าน Telegram Bot

| คำสั่ง | ความหมาย |
|---|---|
| `/now` | กวาดข้อมูลใหม่ทันที + สรุปด้วย AI + ส่งเข้าแชท |
| `/status` | ดูกวาดล่าสุด / ส่งล่าสุด / โมเดล |
| `/help` | วิธีใช้ |

บอทตอบเฉพาะ `TELEGRAM_CHAT_ID` ที่ลงทะเบียนใน `config.env` เท่านั้น

## ย้ายหน้างาน (hotspot) — IP เปลี่ยนไม่เป็นไร

```bash
sudo ./setup_hotspot.sh "ชื่อHotspot" "รหัสผ่าน"   # รันบนทั้งสองเครื่องก่อนไปงาน
```

การหาเครื่องต่อกันใช้ลำดับ: mDNS (`.local`) → cached IP → Cloudflare tunnel
จึงไม่ต้องรู้ IP ล่วงหน้า และทดสอบทันทีด้วย `/now` จาก Telegram

## หลักระบบปฏิบัติการที่ประยุกต์

- **Process Management** — collector คุม timeout ทุก fetcher, systemd จัดการ service + auto-restart
- **Scheduling** — systemd timer (กวาดทุกชม. 22:00–07:00, สรุป 07:05, retry 07:40)
- **Background Services** — daemon ทำงานต่อเนื่อง 24/7 บนอุปกรณ์ทรัพยากรจำกัด
- **Resource Management** — fetcher ทีละตัว, timeout ทุก request, โมเดลขนาดเหมาะกับ RAM
- **Security** — SSRF allowlist ทุก request, credential แยกไฟล์ config.env (chmod 600), bot จำกัด chat_id เดียว

## Troubleshooting

```bash
journalctl -u morning-brief-worker -n 30   # log ฝั่ง Pi 4
journalctl -u morning-brief-brain -n 30    # log ฝั่ง Pi 5
journalctl -u mb-bot -n 30                 # log บอท
systemctl list-timers | grep brief         # ดูตาราง
ollama list && ollama ps                   # ดูโมเดล
```
