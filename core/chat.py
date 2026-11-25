"""Chat logging: Twitch live (anonymous IRC), YouTube live and VOD replays (chat-downloader)."""
import json
import random
import socket
import threading
import time

from . import db


class LiveChatLogger(threading.Thread):
    """Writes {"ts": unix_time, "u": user, "m": message} lines while a stream is live."""

    def __init__(self, platform, url, channel, out_path):
        super().__init__(daemon=True)
        self.platform, self.url, self.channel, self.out_path = platform, url, channel, out_path
        self.stop_event = threading.Event()
        self.count = 0

    def stop(self):
        self.stop_event.set()

    def _write(self, f, user, msg, ts=None):
        f.write(json.dumps({"ts": ts or time.time(), "u": user, "m": msg}, ensure_ascii=False) + "\n")
        f.flush()
        self.count += 1

    def run(self):
        fails = 0
        with open(self.out_path, "a", encoding="utf-8") as f:
            while not self.stop_event.is_set():
                before = self.count
                try:
                    if self.platform == "twitch":
                        self._twitch(f)
                    else:
                        self._youtube(f)
                except Exception as e:
                    if self.stop_event.is_set():
                        break
                    fails = 0 if self.count > before else fails + 1
                    if fails in (1, 10):
                        db.log(f"Chat for {self.channel} disconnected ({e}); retrying in background", "warn")
                if self.platform != "twitch" and self.count == 0:
                    # YouTube chat not available (no chat-downloader / chat off): don't spin
                    self.stop_event.wait(60)
                else:
                    self.stop_event.wait(min(60, 5 * max(1, fails)))

    def _twitch(self, f):
        sock = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
        sock.settimeout(1.0)
        nick = f"justinfan{random.randint(10000, 99999)}"  # anonymous read-only login
        sock.sendall(f"PASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{self.channel.lower()}\r\n".encode())
        buf = b""
        last_data = time.time()
        try:
            while not self.stop_event.is_set():
                try:
                    data = sock.recv(8192)
                    if not data:
                        raise ConnectionError("closed")
                    last_data = time.time()
                except socket.timeout:
                    if time.time() - last_data > 360:
                        raise ConnectionError("no data for 6 min")
                    continue
                buf += data
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    text = line.decode("utf-8", errors="ignore")
                    if text.startswith("PING"):
                        sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif " PRIVMSG #" in text:
                        user = text[1:text.find("!")] if text.startswith(":") else ""
                        msg = text.split(" :", 1)[1] if " :" in text else ""
                        self._write(f, user, msg)
        finally:
            sock.close()

    def _youtube(self, f):
        try:
            from chat_downloader import ChatDownloader
        except ImportError:
            db.log("YouTube chat needs chat-downloader (pip install chat-downloader); using audio only", "warn")
            self.stop_event.wait(3600)
            return
        chat = ChatDownloader().get_chat(self.url)
        for m in chat:
            if self.stop_event.is_set():
                break
            ts = m.get("timestamp")
            self._write(f, (m.get("author") or {}).get("name", ""), m.get("message") or "",
                        ts / 1e6 if ts else None)


def download_vod_chat(url, out_path, max_seconds=900):
    """Save a VOD's chat replay as {"t": seconds_into_video, ...}. Returns message count."""
    try:
        from chat_downloader import ChatDownloader
    except ImportError:
        db.log("chat-downloader not installed; clipping this VOD from audio only", "warn")
        return 0
    count = 0
    started = time.time()
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            for m in ChatDownloader().get_chat(url):
                t = m.get("time_in_seconds")
                if t is None:
                    continue
                f.write(json.dumps({"t": t, "u": (m.get("author") or {}).get("name", ""),
                                    "m": m.get("message") or ""}, ensure_ascii=False) + "\n")
                count += 1
                if count % 5000 == 0:
                    db.log(f"  ...{count} chat messages downloaded")
                if time.time() - started > max_seconds:
                    db.log("Chat download taking too long; using what we have", "warn")
                    break
    except Exception as e:
        db.log(f"Couldn't get VOD chat ({e}); using audio only for missing parts", "warn")
    return count
