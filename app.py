#!/usr/bin/env python3
"""telegram-digest web app — http://localhost:8765

Setup (API keys + Telegram login), choosing groups/topics, browsing exported
messages with links back to Telegram, and reading digests Claude writes to
digests/*.json. Also exports new messages every 2 hours in the background.
Listens on 127.0.0.1 only.
"""
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telethon import errors
from telethon.utils import get_display_name

import export as core

PORT = int(os.environ.get("TGD_PORT", "8765"))
UI = core.ROOT / "ui.html"
DIGESTS = core.ROOT / "digests"
PREFS = core.ROOT / "what-matters.md"
SETTINGS = core.ROOT / "settings.json"
FETCH_REQUEST = core.ROOT / "fetch-now"   # an AI assistant creates this file to ask for a fetch
SERVICE_LABELS = {"local.telegram-digest", "com.michal.telegram-digest"}
FETCH_CHOICES = (30, 60, 120, 240, 480)
log = core.log

PREFS_TEMPLATE = """# What matters to me

Your AI assistant reads this before writing each digest, and adds to it when you
tell it what you do or don't care about. Edit it freely.

## Always put in "Needs attention"
- Anything that mentions me or asks me something directly
- Requests for help, deadlines, and decisions that affect everyone

## Usually not important

## People and topics I follow closely

## Feedback from the digest
"""


def load_settings():
    try:
        st = json.loads(SETTINGS.read_text())
    except Exception:
        st = {}
    st.setdefault("fetch_every_minutes", 120)
    st.setdefault("notify", True)
    st.setdefault("last_seen_digest", None)
    st.setdefault("notified_digests", [])
    return st


def save_settings(st):
    SETTINGS.write_text(json.dumps(st, indent=1))


def fetch_every_s():
    return int(load_settings()["fetch_every_minutes"]) * 60


def load_prefs():
    if not PREFS.exists():
        PREFS.write_text(PREFS_TEMPLATE, encoding="utf-8")
    return PREFS.read_text(encoding="utf-8")


def add_feedback(kind, text, topic):
    label = {"less": "Not important to me", "more": "Flag things like this"}[kind]
    text = re.sub(r"\*\*", "", re.sub(r"\s+", " ", str(text))).strip()[:300]
    line = f'- {dt.date.today():%d %b}: {label}: "{text}"' + (f" ({topic})" if topic else "")
    s = load_prefs().rstrip()
    if "## Feedback from the digest" not in s:
        s += "\n\n## Feedback from the digest"
    PREFS.write_text(s + "\n" + line + "\n", encoding="utf-8")


def notify(title, text):
    """Native macOS notification (no-op elsewhere)."""
    if sys.platform != "darwin":
        return
    q = lambda v: '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e", f"display notification {q(text)} with title {q(title)}"],
                       timeout=10, check=False, capture_output=True)
    except Exception:
        pass


class Telegram:
    """Owns the one Telegram connection, on its own asyncio thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.phone = None
        self.me = None
        self.exporting = False
        self.last_result = None
        self.last_error = None
        self.submit(self._scheduler())

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call(self, coro, timeout=600):
        return self.submit(coro).result(timeout)

    async def _client(self):
        if self.client is None:
            cfg = core.load_env()
            if not core.has_keys(cfg):
                return None
            self.client = core.make_client(cfg)
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    async def _authorized_client(self):
        c = await self._client()
        if c is None or not await c.is_user_authorized():
            raise UserError("Not logged in to Telegram yet — finish Setup first.")
        return c

    async def reset(self):
        if self.client is not None:
            await self.client.disconnect()
        self.client, self.me, self.phone = None, None, None

    async def status(self):
        st = core.load_state()
        last = core.last_export_time()
        out = {
            "keys": core.has_keys(), "authorized": False, "me": None,
            "code_sent": self.phone is not None,
            "selected": len(core.load_selection()["groups"]),
            "last_export": st.get("last_export"), "last_count": st.get("last_count"),
            "next_export": (last + dt.timedelta(seconds=fetch_every_s())).isoformat() if last else None,
            "interval_hours": fetch_every_s() / 3600,
            "fetch_every_minutes": fetch_every_s() // 60,
            "fetch_requested": FETCH_REQUEST.exists(),
            "background": os.environ.get("XPC_SERVICE_NAME", "") in SERVICE_LABELS or os.getppid() == 1,
            "exporting": self.exporting,
            "last_result": self.last_result, "last_error": self.last_error,
        }
        if out["keys"]:
            try:
                c = await self._client()
                out["authorized"] = await c.is_user_authorized()
                if out["authorized"]:
                    if self.me is None:
                        self.me = get_display_name(await c.get_me())
                    out["me"] = self.me
            except Exception as e:
                out["last_error"] = f"Can't reach Telegram: {e}"
        return out

    async def send_code(self, phone):
        c = await self._client()
        if c is None:
            raise UserError("Save your API keys first.")
        await c.send_code_request(phone)
        self.phone = phone
        return {"ok": True}

    async def sign_in_code(self, code):
        c = await self._client()
        if not self.phone:
            raise UserError("Enter your phone number first.")
        try:
            await c.sign_in(phone=self.phone, code=code)
        except errors.SessionPasswordNeededError:
            return {"need_password": True}
        core.secure_session()
        self.phone = None
        return {"ok": True}

    async def sign_in_password(self, password):
        c = await self._client()
        await c.sign_in(password=password)
        core.secure_session()
        self.phone = None
        return {"ok": True}

    async def groups(self):
        return await core.list_groups(await self._authorized_client())

    async def topics(self, gid):
        return await core.list_topics(await self._authorized_client(), gid)

    async def export(self, rebuild_days=None):
        if self.exporting:
            return {"busy": True}
        self.exporting = True
        try:
            c = await self._authorized_client()
            self.last_result = await core.export(c, rebuild_days=rebuild_days)
            self.last_error = None
            return self.last_result
        except UserError:
            raise
        except Exception as e:
            self.last_error = f"Export failed: {e}"
            log(traceback.format_exc())
            raise
        finally:
            self.exporting = False

    async def _scheduler(self):
        await asyncio.sleep(15)
        retry_at = 0.0
        while True:
            try:
                check_new_digests()
                requested = FETCH_REQUEST.exists()
                last = core.last_export_time()
                due = requested or last is None or core.load_state().get("needs_rebuild") or \
                    (dt.datetime.now(dt.timezone.utc) - last).total_seconds() >= fetch_every_s()
                if due and time.time() >= retry_at and core.has_keys() and core.load_selection()["groups"]:
                    c = await self._client()
                    if await c.is_user_authorized():
                        if requested:
                            FETCH_REQUEST.unlink()
                        try:
                            await self.export()
                        except Exception:
                            retry_at = time.time() + 300  # back off after a failure
            except Exception:
                log(traceback.format_exc())
            await asyncio.sleep(30)  # wall-clock checks, so it catches up after sleep


class UserError(Exception):
    pass


TG = None


def _read_digests():
    out = []
    if DIGESTS.is_dir():
        for f in DIGESTS.glob("*.json"):
            try:
                out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                continue
    out.sort(key=lambda x: (x[1].get("to") or "", x[0]), reverse=True)
    return out


def list_digests():
    st = load_settings()
    seen = st.get("last_seen_digest")
    items = _read_digests()
    seen_to = next((d.get("to") for n, d in items if n == seen), None)
    out = []
    for name, d in items:
        n_att = sum(len(g.get("highlights") or []) for g in d.get("groups") or [])
        out.append({"name": name, "from": d.get("from"), "to": d.get("to"), "title": d.get("title"),
                    "attention": n_att, "new": seen is None or (seen_to is not None and (d.get("to") or "") > seen_to)})
    return out


def check_new_digests():
    """Notify once about each digest that appeared since the app started watching."""
    st = load_settings()
    known = set(st.get("notified_digests") or [])
    items = _read_digests()
    fresh = [(n, d) for n, d in items if n not in known]
    if not fresh:
        return
    if known and st.get("notify", True):   # don't notify for digests that existed before the first check
        name, d = fresh[0]
        att = [h.get("text", "") for g in d.get("groups") or [] for h in (g.get("highlights") or [])]
        text = (f"{len(att)} need attention: " + re.sub(r"\*\*", "", att[0])) if att else "No urgent items."
        notify("New Telegram digest", text[:180])
    st["notified_digests"] = sorted(known | {n for n, _ in items})[-500:]
    save_settings(st)


def parse_time(s, default):
    if not s:
        return default
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.astimezone()


class Handler(BaseHTTPRequestHandler):
    server_version = "telegram-digest"

    def log_message(self, fmt, *args):  # keep the log quiet
        pass

    # --- helpers ---
    def _allowed(self):
        host = self.headers.get("Host", "")
        ok_hosts = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
        if host not in ok_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in ok_hosts}:
            return False
        return True

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _run(self, fn):
        try:
            self._send(200, fn())
        except UserError as e:
            self._send(400, {"error": str(e)})
        except errors.RPCError as e:
            self._send(400, {"error": f"Telegram says: {e}"})
        except Exception as e:
            log(traceback.format_exc())
            self._send(500, {"error": str(e)})

    # --- routes ---
    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p in ("/", "/index.html"):
            return self._send(200, UI.read_bytes(), "text/html")
        routes = {
            "/api/status": lambda: TG.call(TG.status()),
            "/api/groups": lambda: TG.call(TG.groups()),
            "/api/topics": lambda: TG.call(TG.topics(q["gid"])),
            "/api/selection": core.load_selection,
            "/api/dates": core.export_dates,
            "/api/digests": list_digests,
            "/api/digest": lambda: self._digest(q.get("name", "")),
            "/api/messages": lambda: self._messages(q),
            "/api/preferences": lambda: {"text": load_prefs()},
            "/api/settings": load_settings,
        }
        if p in routes:
            return self._run(routes[p])
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed() or "application/json" not in self.headers.get("Content-Type", ""):
            return self._send(403, {"error": "forbidden"})
        p = urlparse(self.path).path
        try:
            body = self._json_body()
        except Exception:
            return self._send(400, {"error": "bad json"})
        routes = {
            "/api/keys": lambda: self._keys(body),
            "/api/login/phone": lambda: TG.call(TG.send_code(body["phone"].strip())),
            "/api/login/code": lambda: TG.call(TG.sign_in_code(str(body["code"]).strip())),
            "/api/login/password": lambda: TG.call(TG.sign_in_password(body["password"])),
            "/api/login/reset": lambda: self._login_reset(),
            "/api/selection": lambda: self._save_selection(body),
            "/api/export": lambda: TG.call(TG.export(body.get("rebuild_days"))),
            "/api/preferences": lambda: self._save_prefs(body),
            "/api/feedback": lambda: self._feedback(body),
            "/api/settings": lambda: self._save_settings(body),
            "/api/seen": lambda: self._seen(body),
        }
        if p in routes:
            return self._run(routes[p])
        self._send(404, {"error": "not found"})

    # --- route bodies ---
    def _keys(self, body):
        api_id, api_hash = str(body.get("api_id", "")).strip(), str(body.get("api_hash", "")).strip()
        if not re.fullmatch(r"\d{3,12}", api_id) or not re.fullmatch(r"[0-9a-f]{32}", api_hash):
            raise UserError("api_id should be a number and api_hash 32 hex characters.")
        core.save_env(api_id, api_hash)
        TG.call(TG.reset())
        return {"ok": True}

    def _save_prefs(self, body):
        text = str(body.get("text", ""))
        if len(text) > 50000:
            raise UserError("That's too long.")
        PREFS.write_text(text, encoding="utf-8")
        return {"ok": True}

    def _feedback(self, body):
        kind = body.get("kind")
        if kind not in ("less", "more") or not body.get("text"):
            raise UserError("bad feedback")
        add_feedback(kind, body["text"], str(body.get("topic") or ""))
        return {"ok": True}

    def _save_settings(self, body):
        st = load_settings()
        if "fetch_every_minutes" in body:
            m = int(body["fetch_every_minutes"])
            if m not in FETCH_CHOICES:
                raise UserError("Pick one of the offered intervals.")
            st["fetch_every_minutes"] = m
        if "notify" in body:
            st["notify"] = bool(body["notify"])
        save_settings(st)
        return st

    def _seen(self, body):
        name = str(body.get("name", ""))
        if not re.fullmatch(r"[\w\-.]+", name):
            raise UserError("bad digest name")
        st = load_settings()
        items = _read_digests()
        cur = next((d.get("to") for n, d in items if n == st.get("last_seen_digest")), None)
        new = next((d.get("to") for n, d in items if n == name), None)
        if new and (cur is None or new > cur):
            st["last_seen_digest"] = name
            save_settings(st)
        return {"ok": True}

    def _login_reset(self):
        TG.phone = None
        return {"ok": True}

    def _save_selection(self, body):
        groups = {}
        for gid, g in (body.get("groups") or {}).items():
            if not re.fullmatch(r"-?\d+", gid):
                continue
            topics = g.get("topics", "all")
            if topics != "all":
                topics = sorted({int(t) for t in topics})
                if not topics:
                    continue
            groups[gid] = {"title": str(g.get("title", "")), "forum": bool(g.get("forum")), "topics": topics}
        core.save_selection({"groups": groups})
        return {"ok": True, "selected": len(groups)}

    def _digest(self, name):
        if not re.fullmatch(r"[\w\-.]+", name):
            raise UserError("bad digest name")
        f = DIGESTS / f"{name}.json"
        if not f.exists():
            raise UserError("no such digest")
        return json.loads(f.read_text(encoding="utf-8"))

    def _messages(self, q):
        now = dt.datetime.now().astimezone()
        end = parse_time(q.get("to"), now)
        start = parse_time(q.get("from"), end - dt.timedelta(days=1))
        return core.read_messages(start, end)


def main():
    global TG
    TG = Telegram()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"telegram-digest running on http://localhost:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
