import asyncio
import io
import json
import os
import sys
import tempfile
import time
import wave

import numpy as np
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import FloodWaitError

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

# ========== CONFIG (Railway env vars) ==========
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

AUDIO_DURATION = 20
AUDIO_AMPLITUDE = 0.95
TONE_FREQUENCY = 8500

CONFIG_FILE = "bot_config.json"

bot_state = {
    "target_id": None,
    "target_name": None,
    "is_attacking": False,
    "app": None,
    "pytgcalls": None,
}
# ================================================

# ✅ FIX 2: save_config() – stray word "mutations" hata diya
def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "target_id": bot_state["target_id"],
            "target_name": bot_state["target_name"],
            "duration": AUDIO_DURATION,
            "tone": TONE_FREQUENCY,
            "amplitude": AUDIO_AMPLITUDE,
        }, f, indent=4)

def load_config():
    global AUDIO_DURATION, AUDIO_AMPLITUDE, TONE_FREQUENCY
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                d = json.load(f)
            bot_state["target_id"] = d.get("target_id")
            bot_state["target_name"] = d.get("target_name")
            AUDIO_DURATION = d.get("duration", AUDIO_DURATION)
            AUDIO_AMPLITUDE = d.get("amplitude", AUDIO_AMPLITUDE)
            TONE_FREQUENCY = d.get("tone", TONE_FREQUENCY)
            print("[✓] Config loaded.")
        except Exception:
            print("[!] Config corrupted, defaults.")

def generate_noise(duration_sec, noise_amp, tone_freq, sample_rate=48000):
    """White noise + high tone + pulse — VC disturb audio."""
    samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, samples, endpoint=False)
    noise = np.random.normal(0, noise_amp, samples).astype(np.float32)
    tone = 0.4 * np.sin(2 * np.pi * tone_freq * t)
    pulse = 0.3 * (0.5 + 0.5 * np.sin(2 * np.pi * 20 * t))
    pcm = (np.clip(noise + tone + pulse, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    buf.seek(0)
    return buf

# ---------- HANDLERS ----------
def owner_only(func):
    async def wrapper(event):
        if event.sender_id != OWNER_ID:
            await event.reply("❌ Unauthorized!")
            return
        return await func(event)
    return wrapper

@owner_only
async def start_cmd(event):
    await event.reply(
        "🤖 **VC Audio Attack Bot**\n\n"
        "🎯 `/target <link>` — Target group set\n"
        "⚔️ `/attack` — VC join + noise\n"
        "⏹️ `/stop` — Rok do\n"
        "📊 `/status` — Status\n"
        "⚙️ `/set duration 30` — Settings"
    )

@owner_only
async def status_cmd(event):
    await event.reply(
        f"📊 Target: {bot_state['target_name'] or 'Not set'}\n"
        f"Attack: {'✅ Active' if bot_state['is_attacking'] else '❌ Idle'}\n"
        f"Audio: {AUDIO_DURATION}s | Tone: {TONE_FREQUENCY}Hz"
    )

@owner_only
async def target_cmd(event):
    parts = event.raw_text.split()
    if len(parts) < 2:
        await event.reply("❌ Usage: /target <link_or_id>")
        return
    link = parts[1].strip()
    app = bot_state["app"]
    try:
        if link.startswith(("http", "t.me")):
            uname = link.rstrip("/").split("/")[-1]
            if "t.me/+" in link:
                await app(ImportChatInviteRequest(uname.lstrip("+")))
            else:
                try:
                    await app(JoinChannelRequest(uname))
                except Exception:
                    pass
            try:
                chat = await app.get_entity(int(uname))
            except ValueError:
                chat = await app.get_entity("@" + uname.lstrip("+"))
        else:
            chat = await app.get_entity(int(link))

        bot_state["target_id"] = chat.id
        bot_state["target_name"] = getattr(chat, "title", str(chat.id))
        save_config()
        await event.reply(f"[✅] Target: **{bot_state['target_name']}**\nID: `{chat.id}`")
    except FloodWaitError as e:
        await event.reply(f"[!] Flood wait: {e.seconds}s")
    except Exception as e:
        await event.reply(f"[!] Error: {e}")

@owner_only
async def attack_cmd(event):
    if bot_state["is_attacking"]:
        await event.reply("⚠️ Attack already running!")
        return
    if not bot_state["target_id"]:
        await event.reply("❌ No target! /target pehle set karo.")
        return

    chat_id = bot_state["target_id"]
    await event.reply(f"🚀 **Attacking {bot_state['target_name']}...**")
    bot_state["is_attacking"] = True
    audio_path = None

    try:
        buf = generate_noise(AUDIO_DURATION, AUDIO_AMPLITUDE, TONE_FREQUENCY)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(buf.read())
            audio_path = tf.name

        await bot_state["pytgcalls"].play(chat_id, MediaStream(audio_path))
        await event.reply(f"[✅] Noise playing for {AUDIO_DURATION}s")
        await asyncio.sleep(AUDIO_DURATION + 2)

        try:
            await bot_state["pytgcalls"].leave_call(chat_id)
        except Exception:
            pass
        await event.reply("[✅] Attack complete!")
    except Exception as e:
        await event.reply(f"[❌] Error: {e}")
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        bot_state["is_attacking"] = False

@owner_only
async def stop_cmd(event):
    try:
        await bot_state["pytgcalls"].leave_call(bot_state["target_id"])
        await event.reply("[⏹️] Stopped.")
    except Exception:
        await event.reply("ℹ️ Nothing active.")
    bot_state["is_attacking"] = False

# ✅ FIX 3: set_cmd() – stray "byte" hata diya, else se pehle kuch nahi
@owner_only
async def set_cmd(event):
    global AUDIO_DURATION, TONE_FREQUENCY
    parts = event.raw_text.split()
    if len(parts) < 3 or parts[1] not in ("duration", "tone"):
        await event.reply("Usage: /set duration 30  |  /set tone 8500")
        return
    try:
        if parts[1] == "duration":
            AUDIO_DURATION = max(5, int(parts[2]))
        else:
            TONE_FREQUENCY = max(3000, min(15000, int(parts[2])))
        save_config()
        await event.reply(f"[✅] {parts[1]} = {parts[2]}")
    except Exception:
        await event.reply("[!] Invalid value")

# ---------- KEEP-ALIVE SERVER (Railway) ----------
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
    print("🚀 VC Audio Attack Bot starting...")

    if not SESSION_STRING or not API_ID or not API_HASH or not OWNER_ID:
        print("[!] ERROR: SESSION_STRING, API_ID, API_HASH, OWNER_ID set karo!")
        sys.exit(1)

    # ✅ FIX 1: load_bot_config() → load_config()
    load_config()

    app = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await app.start()
    user = await app.get_me()
    print(f"[👤] Logged in: {user.first_name} (ID: {user.id})")

    pytgcalls = PyTgCalls(app)
    await pytgcalls.start()
    bot_state["app"] = app
    bot_state["pytgcalls"] = pytgcalls

    patterns = {
        r"^/start(/@\w+)?(\s|$)": start_cmd,
        r"^/status(/@\w+)?(\s|$)": status_cmd,
        r"^/target(/@\w+)?(\s|$)": target_cmd,
        r"^/attack(/@\w+)?(\s|$)": attack_cmd,
        r"^/stop(/@\w+)?(\s|$)": stop_cmd,
        r"^/set(/@\w+)?(\s|$)": set_cmd,
    }
    for pat, fn in patterns.items():
        @app.on(events.NewMessage(pattern=pat))
        async def handler(event, f=fn):
            await f(event)

    print("✅ BOT RUNNING! Commands: /target /attack /stop")
    asyncio.create_task(web_server())
    await app.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
