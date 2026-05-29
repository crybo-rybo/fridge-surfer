# Remy — Deployment Guide

This document covers everything needed to go from a stock Jetson Orin Nano Super to a running Remy bot. For Mac development workflow, see [README.md](README.md). For background and design rationale, see the Spec, Requirements, and Hardening documents in the project vault.

The whole thing should take 1–2 hours of focused work, most of which is waiting for `apt`, model downloads, and the first cold model load.

---

## 1. Hardware Checklist

Before you start, gather:

- NVIDIA Jetson Orin Nano Super dev kit (8GB unified memory).
- microSD card (64GB+ recommended) flashed with JetPack 6.x, or NVMe SSD if your carrier board supports it.
- USB or CSI camera capable of capturing the fridge interior.
- 5V/3A USB-C power supply (the Orin Nano Super is power-hungry — don't reuse a phone charger).
- Ethernet cable (wired install is the easier path for first boot; Wi-Fi works too).
- A monitor, keyboard, and mouse for initial setup. After SSH is up you can run headless.

You will also need, on your laptop:

- The Telegram chat ID you want the bot to talk to.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- An SSH key pair (`~/.ssh/id_ed25519.pub` is fine).

---

## 2. Base OS Setup

### 2.1 Flash JetPack 6.x

Use NVIDIA's [SDK Manager](https://developer.nvidia.com/sdk-manager) or write the official JetPack image directly to the SD card. Boot the Jetson with monitor + keyboard attached and complete the Ubuntu first-run wizard. Create your admin user (we'll call it `fridge` below — substitute your own).

### 2.2 System updates

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

### 2.3 Static IP or DHCP reservation

Reserve an IP for the Jetson on your router so `ssh remy.local` (or `ssh 192.168.1.X`) always reaches it. Avoids surprises after a router reboot.

### 2.4 SSH from your workstation

Copy your public key to the Jetson while passwords are still enabled:

```bash
ssh-copy-id fridge@<jetson-ip>
```

Verify key-only login works before disabling passwords in §6.2.

---

## 3. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

The installer drops a systemd unit at `/etc/systemd/system/ollama.service` and starts the service. By default Ollama binds to `127.0.0.1:11434` — that's the correct setting; don't change it.

Verify:

```bash
sudo systemctl status ollama
sudo ss -tlnp | grep 11434   # should show 127.0.0.1:11434
ollama --version
```

Verify Ollama is **0.13.1 or newer** — `ministral-3:3b` requires it:

```bash
ollama --version   # must be >= 0.13.1
```

If you're on an older build, re-run the install script from §3 or upgrade via your package manager, then restart Ollama.

### 3.1 Pull the models

```bash
ollama pull qwen3-vl:2b
ollama pull ministral-3:3b
```

This downloads ~5 GB total. On a slow connection, run it overnight.

Sanity check both models respond:

```bash
ollama run ministral-3:3b "Suggest a one-line dinner using eggs and broccoli."
# Ctrl-D to exit
```

For vision, the Phase 0 smoke test from the Spec is worth doing now — take a real photo of your fridge, copy it to the Jetson, and run:

```bash
ollama run qwen3-vl:2b "List all visible food items as a JSON array of strings." < fridge.jpg
```

If the output isn't a usable JSON list, fix the model choice or prompt before going further. The tolerant parser in `vision.py` handles a lot, but garbage-in still gets garbage-out.

---

## 4. Create the `remy` Service User

The bot should not run as your admin user. Create a dedicated unprivileged account:

```bash
sudo useradd -m -s /bin/bash remy
sudo usermod -aG video remy   # camera access
```

The `video` group is what lets the bot user open `/dev/video0` for camera capture.

---

## 5. Install the Application

Switch to the service user for everything from here on:

```bash
sudo -iu remy
```

### 5.1 Clone the repo

```bash
cd ~
git clone <repo-url> remy
cd remy
```

### 5.2 Create and populate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.3 Configure environment variables

```bash
cp .env.example .env
nano .env
```

Fill in the required values:

| Variable | Notes |
|---|---|
| `OLLAMA_HOST` | Leave at `http://localhost:11434`. |
| `OLLAMA_KEEP_ALIVE` | `30m` keeps the **chef** model warm between requests. Vision always unloads immediately after each call to leave room for the chef model on 8 GB devices. |
| `VISION_NUM_CTX` | `2048` keeps the VLM context modest while leaving room for image tokens. |
| `CHEF_NUM_CTX` | `2048` is enough for ingredient lists, recent recipe summaries, and one concise recipe. |
| `VISION_MODEL` | `qwen3-vl:2b` |
| `CHEF_MODEL` | `ministral-3:3b` |
| `DB_PATH` | `/home/remy/remy/remy.db` (absolute path is safer under systemd). |
| `RECENT_RECIPES_N` | `5` is a sane default. |
| `TELEGRAM_BOT_TOKEN` | From BotFather. |
| `TELEGRAM_ALLOWED_CHAT_ID` | Your personal chat ID — message [@userinfobot](https://t.me/userinfobot) to find it. |
| `SCHEDULED_SCAN_TIME` | `17:00` for a 5pm daily push. 24h local time. |
| `CAMERA_INDEX` | `0` for the first USB camera, or a full GStreamer pipeline string for CSI. |

Lock the file down so the Telegram token isn't world-readable:

```bash
chmod 600 .env
```

### 5.4 Camera sanity check

Still as `remy`, test the camera in isolation before letting systemd touch it:

```bash
python -c "import cv2; cap = cv2.VideoCapture(0); ok, frame = cap.read(); print('ok:', ok, 'shape:', None if frame is None else frame.shape); cap.release()"
```

You want `ok: True` and a shape like `(480, 640, 3)`. If `ok: False`, double-check `CAMERA_INDEX`, that the device shows up under `ls /dev/video*`, and that the `remy` user is in the `video` group (you may need to log out and back in for the group to take effect).

### 5.5 Smoke test end-to-end via the debug CLI

```bash
python -m remy.debug_cli
```

Inside the REPL:

```
/scan        → captures from the camera, prints the ingredient list
/recipe      → full pipeline, prints a recipe
```

If both work, you're ready to install the systemd unit. Exit the CLI (`Ctrl-D`).

---

## 6. System Hardening

The full rationale lives in `Remy-Hardening.md`. The condensed checklist below is what you actually need to type at the device.

### 6.1 UFW firewall (default-deny inbound, LAN-only SSH)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp   # adjust to your subnet
sudo ufw enable
sudo ufw status verbose
```

### 6.2 SSH key-only authentication

Edit `/etc/ssh/sshd_config`:

```
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
AllowUsers fridge
```

Then:

```bash
sudo systemctl restart ssh
```

Verify from your workstation in a new terminal *before* closing your existing session — locking yourself out is the easiest mistake to make here.

### 6.3 Unattended security upgrades

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure unattended-upgrades
```

Enable security-only updates. Do not enable full release upgrades — JetPack/CUDA can break on uncontrolled kernel bumps.

### 6.4 fail2ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
```

Defaults are fine.

### 6.5 (Optional) Tailscale for remote access

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo ufw allow in on tailscale0
```

After this you can SSH from anywhere via `ssh remy@<tailscale-hostname>` with no port forwarding.

---

## 7. systemd Unit

Create `/etc/systemd/system/remy.service`:

```ini
[Unit]
Description=Remy
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=remy
WorkingDirectory=/home/remy/remy
EnvironmentFile=/home/remy/remy/.env
ExecStart=/home/remy/remy/.venv/bin/python -m remy.bot
Restart=on-failure
RestartSec=5

# Light sandboxing
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/remy/remy
ProtectKernelTunables=true
ProtectKernelModules=true

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now remy
sudo systemctl status remy
```

Watch logs:

```bash
sudo journalctl -u remy -f
```

A successful start ends with `Remy is online. Send /help for available commands.` arriving in your Telegram chat.

You can also send a fridge photo captioned `/recipe` or `/scan` to run the pipeline from your phone instead of the mounted camera.

---

## 8. Verification Checklist

Walk through each of these before declaring the deployment done. Each one corresponds to an MVP acceptance criterion in the Requirements doc.

| # | Check | How |
|---|---|---|
| 1 | Bot is running as the service user | `systemctl status remy` shows `Active: active` and `User=remy`. |
| 2 | `/help` lists available commands | Send `/help`; reply includes each Telegram command and what it does. |
| 3 | `/test` works with a test image | Send `/test` from your Telegram client; recipe arrives without touching the camera. |
| 4 | `/recipe` works on demand | Send `/recipe` from your Telegram client; recipe arrives within ~60 s. |
| 5 | `/scan` returns an ingredient list | Send `/scan`; reply is a clean bulleted list. |
| 5b | Photo captioned `/recipe` works | Send a fridge photo with caption `/recipe`; recipe arrives without using the camera. |
| 5c | Photo captioned `/scan` works | Send a fridge photo with caption `/scan`; ingredient list arrives. |
| 6 | Scheduled run fires | Set `SCHEDULED_SCAN_TIME` to two minutes from now, restart the service, wait. |
| 7 | Bot ignores other chats | Message the bot from a different Telegram account; no response. |
| 8 | Reboot survival | `sudo reboot`; after boot, the bot reconnects and sends its startup message. |
| 9 | Firewall posture | `sudo ufw status verbose` shows default-deny inbound and LAN-only SSH. |
| 10 | Ollama is local-only | `sudo ss -tlnp \| grep 11434` shows `127.0.0.1:11434`, not `0.0.0.0`. |
| 11 | No password SSH | `grep -E '^(PasswordAuthentication\|PermitRootLogin)' /etc/ssh/sshd_config` returns `no` on both. |
| 12 | Unattended upgrades active | `sudo systemctl status unattended-upgrades` is active. |

Hit all twelve and Remy is shipped.

---

## 9. Common Operational Tasks

**Restart the bot after a code change:**

```bash
sudo systemctl restart remy
sudo journalctl -u remy -f
```

**Update dependencies:**

```bash
sudo -iu remy
cd ~/remy
source .venv/bin/activate
git pull
pip install -r requirements.txt
exit
sudo systemctl restart remy
```

**Swap models:**

Edit `.env`, change `VISION_MODEL` or `CHEF_MODEL`, then `sudo systemctl restart remy`. If the new model isn't pulled yet, `ollama pull <model>` first.

**Inspect the recipe history:**

```bash
sudo -u remy sqlite3 /home/remy/remy/remy.db \
  "SELECT id, timestamp, rating, substr(recipe_text, 1, 60) FROM recipes ORDER BY id DESC LIMIT 20;"
```

**Tail the logs:**

```bash
sudo journalctl -u remy -n 200 --no-pager
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot never sends startup message | Wrong token or chat ID. | Re-check `.env`, restart service, watch `journalctl`. |
| `/recipe` or `/test` returns "AI models appear to be unavailable" | Ollama not running, model not pulled, outdated Ollama (< 0.13.1 for ministral), or OOM. | `sudo systemctl status ollama`, `ollama list`, `ollama --version`. If logs show vision succeeded but **Chef module failed** with HTTP 500, test the chef model directly: `curl -s http://localhost:11434/api/chat -d '{"model":"ministral-3:3b","messages":[{"role":"user","content":"hello"}],"stream":false}'`. Check `sudo journalctl -u ollama -n 50` for OOM or template errors. Pull/deploy the latest code so vision unloads before chef runs. |
| Chef fails with HTTP 500 but vision works | Vision model still resident + chef load exceeds RAM, or stale ministral blob. | `ollama stop $(ollama ps -q)` then retest chef. `ollama pull ministral-3:3b`. Lower `CHEF_NUM_CTX` if still tight. |
| `/recipe` returns "couldn't access the camera" | Camera device missing, permission, or wrong index. | `ls /dev/video*`, `groups remy`, retest with the snippet in §5.4. |
| First `/recipe` is very slow, second is fast | Cold model load — expected. | Tune `OLLAMA_KEEP_ALIVE` in Ollama's systemd override if you want models to stay resident longer. |
| Bot replies to messages from wrong chat | `TELEGRAM_ALLOWED_CHAT_ID` set wrong (e.g. negative ID for a group not pasted with sign). | Fix in `.env`, restart. |
| Memory pressure with both models loaded | 8GB unified memory is tight. | Lower `VISION_NUM_CTX` / `CHEF_NUM_CTX` first. If still tight, lower `OLLAMA_KEEP_ALIVE` so models swap on demand. |

---

## 11. What's Intentionally Not Here

- No reverse proxy / nginx — the bot has no HTTP listener.
- No full disk encryption — recipe history isn't sensitive.
- No port forwarding — Telegram long polling is outbound-only.
- No webhook mode — see Hardening doc for why we deliberately skip it.

If you find yourself reaching for any of these, re-read the Hardening doc first. The "outbound-only, behind NAT" posture is load-bearing for the whole security model.
