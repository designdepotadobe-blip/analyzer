"""
Discord channel reader — reads message history and listens live for new messages
from a specific channel using a user token.

Usage:
    python discord_reader.py              # fetch last 50 messages + go live
    python discord_reader.py --history 200  # fetch last 200 messages only, then exit
    python discord_reader.py --live        # skip history, only listen live

Credentials are read from .env:
    DISCORD_TOKEN=<your user token>
    DISCORD_CHANNEL_ID=<channel id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

import requests
import websocket
from dotenv import load_dotenv

# Fix Windows console encoding for Unicode characters
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf-16'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")

if not TOKEN or not CHANNEL_ID:
    sys.exit("Set DISCORD_TOKEN and DISCORD_CHANNEL_ID in .env")

HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}
API = "https://discord.com/api/v10"


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_msg(msg: dict) -> str:
    author = msg.get("author", {}).get("username", "?")
    ts_raw = msg.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts = ts_raw[:16]
    content = msg.get("content", "").strip()
    attachments = msg.get("attachments", [])
    embeds = msg.get("embeds", [])

    lines = [f"\n[{ts}] {author}"]
    if content:
        lines.append(content)
    for att in attachments:
        url = att.get("url", "")
        name = att.get("filename", "attachment")
        lines.append(f"  IMAGE: {name}  →  {url}")
    for emb in embeds:
        title = emb.get("title", "")
        desc = emb.get("description", "")
        img = (emb.get("image") or {}).get("url", "")
        if title:
            lines.append(f"  [embed] {title}")
        if desc:
            lines.append(f"  {desc[:200]}")
        if img:
            lines.append(f"  IMAGE: {img}")
    return "\n".join(lines)


# ── REST: fetch history ────────────────────────────────────────────────────────

def fetch_history(limit: int = 50) -> list[dict]:
    """Fetch up to `limit` recent messages (max 100 per request)."""
    messages = []
    before = None
    remaining = limit
    while remaining > 0:
        batch = min(remaining, 100)
        params = {"limit": batch}
        if before:
            params["before"] = before
        r = requests.get(f"{API}/channels/{CHANNEL_ID}/messages", headers=HEADERS, params=params)
        if r.status_code == 401:
            sys.exit("401 Unauthorized — token is invalid or expired")
        if r.status_code == 403:
            sys.exit("403 Forbidden — you don't have access to this channel")
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            break
        batch_msgs = r.json()
        if not batch_msgs:
            break
        messages.extend(batch_msgs)
        before = batch_msgs[-1]["id"]
        remaining -= len(batch_msgs)
        if len(batch_msgs) < batch:
            break
    return list(reversed(messages))  # oldest first


# ── WebSocket: live listener ────────────────────────────────────────────────────

class DiscordGateway:
    GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"

    def __init__(self, token: str, channel_id: str, on_message):
        self.token = token
        self.channel_id = channel_id
        self.on_message = on_message
        self._ws = None
        self._heartbeat_interval = None
        self._hb_thread = None
        self._sequence = None

    def run(self):
        self._ws = websocket.WebSocketApp(
            self.GATEWAY,
            on_open=self._on_open,
            on_message=self._on_event,
            on_error=lambda ws, e: print(f"Gateway error: {e}"),
            on_close=lambda ws, c, m: print("Gateway closed"),
        )
        self._ws.run_forever()

    def _on_open(self, ws):
        pass  # HELLO triggers identify

    def _on_event(self, ws, raw):
        data = json.loads(raw)
        op = data.get("op")
        self._sequence = data.get("s") or self._sequence

        if op == 10:  # HELLO — start heartbeating + identify
            self._heartbeat_interval = data["d"]["heartbeat_interval"] / 1000.0
            self._hb_thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._hb_thread.start()
            self._identify()

        elif op == 0:  # Dispatch
            t = data.get("t")
            if t == "MESSAGE_CREATE":
                msg = data["d"]
                if msg.get("channel_id") == self.channel_id:
                    self.on_message(msg)

    def _identify(self):
        self._ws.send(json.dumps({
            "op": 2,
            "d": {
                "token": self.token,
                "properties": {"os": "windows", "browser": "chrome", "device": ""},
                "intents": 0,  # user tokens don't use intents
            },
        }))

    def _heartbeat(self):
        while True:
            time.sleep(self._heartbeat_interval)
            if self._ws:
                self._ws.send(json.dumps({"op": 1, "d": self._sequence}))


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=int, default=50, help="messages to fetch from history")
    parser.add_argument("--live", action="store_true", help="skip history, only listen live")
    parser.add_argument("--save", type=str, default="", help="save output to this file")
    args = parser.parse_args()

    out = open(args.save, "w", encoding="utf-8") if args.save else None

    def log(text: str):
        print(text)
        if out:
            out.write(text + "\n")
            out.flush()

    # ── History ───────────────────────────────────────────────────────────────
    if not args.live:
        log(f"Fetching last {args.history} messages from channel {CHANNEL_ID}…")
        msgs = fetch_history(args.history)
        log(f"Got {len(msgs)} messages\n{'─' * 60}")
        for m in msgs:
            log(fmt_msg(m))
        log(f"\n{'─' * 60}")

    if args.history and not args.live:
        log("History done. Add --live to also stream new messages.")
        if out:
            out.close()
        return

    # ── Live ──────────────────────────────────────────────────────────────────
    log("\nConnecting to Discord Gateway for live messages…  (Ctrl+C to stop)\n")

    def on_new(msg):
        log(fmt_msg(msg))

    gw = DiscordGateway(TOKEN, CHANNEL_ID, on_new)
    try:
        gw.run()
    except KeyboardInterrupt:
        log("Stopped.")
    finally:
        if out:
            out.close()


if __name__ == "__main__":
    main()
