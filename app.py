#!/usr/bin/env python3
"""telegram-digest web app — http://localhost:8765

Setup (API keys + Telegram login), choosing groups/topics, browsing exported
messages with links back to Telegram, and reading digests Claude writes to
digests/*.json. Also exports new messages every 2 hours in the background.
Listens on 127.0.0.1 only.
"""
import asyncio
import datetime as dt
import html
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telethon import errors
from telethon.utils import get_display_name

import export as core

PORT = int(os.environ.get("TGD_PORT", "8765"))
API_VERSION = 4          # the page checks this to spot an app that hasn't restarted after an update
CODE_FILES = [os.path.abspath(__file__), os.path.abspath(core.__file__)]


def code_stamp():
    return tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in CODE_FILES)
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


DEFAULTS = {
    "fetch_every_minutes": 120,      # how often to fetch new messages
    "notify": "attention",           # attention | all | off
    "digest_mode": "auto",           # auto | manual
    "digest_engine": "auto",         # auto | claude | codex
    "digest_schedule": "every",      # after_fetch | every | daily
    "digest_every_hours": 4,
    "digest_daily_at": "08:00",
    "digest_period": "since_last",   # since_last | last_24h
    "digest_min_new": 1,
    "phone_send": "all",             # all | attention | off   (Telegram bot)
    "digests_chosen": False,         # guided setup: digest step done
    "claude_model": "",              # "" = Claude Code's own default
    "claude_effort": "",
    "codex_model": "",               # "" = Codex's own default
    "codex_effort": "",
    "digest_photos": True,           # save photo previews and let the digest look at them
}
PHOTO_CAP = 20                       # most photos one digest looks at
CHOICES = {
    "fetch_every_minutes": FETCH_CHOICES,
    "notify": ("attention", "all", "off"),
    "digest_mode": ("auto", "manual"),
    "digest_engine": ("auto", "claude", "codex"),
    "digest_schedule": ("after_fetch", "every", "daily"),
    "digest_every_hours": (1, 2, 4, 8, 12),
    "digest_period": ("since_last", "last_24h"),
    "digest_min_new": (1, 3, 5, 10, 20),
    "phone_send": ("all", "attention", "off"),
    "claude_model": ("", "sonnet", "opus", "haiku", "fable"),
    "claude_effort": ("", "low", "medium", "high", "xhigh", "max"),
    "codex_effort": ("", "minimal", "low", "medium", "high", "xhigh"),
}


def load_settings():
    try:
        st = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if isinstance(st.get("notify"), bool):          # older versions stored on/off
        st["notify"] = "attention" if st["notify"] else "off"
    for k, v in DEFAULTS.items():
        st.setdefault(k, v)
    st.setdefault("last_seen_digest", None)
    st.setdefault("notified_digests", [])
    return st


def save_settings(st):
    core.write_atomic(SETTINGS, json.dumps(st, indent=1))


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


WINDOWS = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # Windows: run helpers without flashing a console
OS_NAME = "windows" if WINDOWS else "mac" if sys.platform == "darwin" else "linux"

# Windows toast through the built-in Windows PowerShell; the text arrives in environment variables
TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:TGD_TITLE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:TGD_TEXT)) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($t)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)
"""


def notify(title, text):
    """Native notification on macOS and Windows (no-op elsewhere)."""
    if WINDOWS:
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", TOAST_PS],
                           env=dict(os.environ, TGD_TITLE=str(title), TGD_TEXT=str(text)),
                           timeout=20, check=False, capture_output=True, creationflags=NO_WINDOW)
        except Exception:
            pass
        return
    if sys.platform != "darwin":
        return
    q = lambda v: '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e", f"display notification {q(text)} with title {q(title)}"],
                       timeout=10, check=False, capture_output=True)
    except Exception:
        pass


# ---------- automatic digests via the person's own AI tool ----------

DSTATE = core.ROOT / ".digest-state.json"
ENGINE_NAMES = {"claude": "Claude Code", "codex": "Codex"}


def windows_path():
    """PATH as Windows has it now, so a tool installed after login is still found."""
    parts = os.environ.get("PATH", "").split(os.pathsep)
    try:
        import winreg
        for root, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(os.pathsep)
            except OSError:
                pass
    except ImportError:
        pass
    home, local, roaming = os.path.expanduser("~"), os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
    parts += [os.path.join(home, ".local", "bin"), os.path.join(home, ".codex", "bin")]
    if roaming:
        parts.append(os.path.join(roaming, "npm"))
    if local:
        parts += [os.path.join(local, "Microsoft", "WinGet", "Links"), os.path.join(local, "Programs", "codex"),
                  os.path.join(local, "OpenAI", "Codex", "bin")]
    return os.pathsep.join(dict.fromkeys(p for p in parts if p))


def tool_path():
    if WINDOWS:
        return windows_path()
    home = os.path.expanduser("~")
    extra = [f"{home}/.local/bin", f"{home}/.claude/local", f"{home}/bin", f"{home}/.npm-global/bin",
             f"{home}/.bun/bin", f"{home}/.volta/bin", f"{home}/.codex/bin", "/opt/homebrew/bin", "/usr/local/bin"]
    nvm = os.path.join(home, ".nvm", "versions", "node")
    if os.path.isdir(nvm):
        extra += [os.path.join(nvm, v, "bin") for v in sorted(os.listdir(nvm), reverse=True)]
    parts = os.environ.get("PATH", "").split(os.pathsep) + extra
    return os.pathsep.join(dict.fromkeys(p for p in parts if p))


def find_engines():
    path = tool_path()
    return {k: shutil.which(k, path=path) for k in ENGINE_NAMES}


def pick_engine(st=None):
    st = st or load_settings()
    found = find_engines()
    pref = st.get("digest_engine", "auto")
    if pref in found:
        return (pref, found[pref]) if found[pref] else (None, None)
    for k in ("claude", "codex"):
        if found[k]:
            return k, found[k]
    return None, None


def load_dstate():
    try:
        return json.loads(DSTATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_dstate(ds):
    core.write_atomic(DSTATE, json.dumps(ds, indent=1))


def newest_digest_to():
    items = _read_digests()
    return items[0][1].get("to") if items else None


PERIODS = ("since_last", "last_24h", "today", "yesterday", "last_3d", "last_7d")


def digest_period(st=None, override=None):
    st = st or load_settings()
    key = override or st.get("digest_period", "since_last")
    now = dt.datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "today":
        return midnight, now
    if key == "yesterday":
        return midnight - dt.timedelta(days=1), midnight
    if key == "last_3d":
        return now - dt.timedelta(days=3), now
    if key == "last_7d":
        return now - dt.timedelta(days=7), now
    last = newest_digest_to()
    if key == "since_last" and last:
        start = dt.datetime.fromisoformat(last)
        if now - start > dt.timedelta(days=7):      # don't let one update cover weeks
            start = now - dt.timedelta(days=7)
        return start, now
    return now - dt.timedelta(days=1), now


DIGEST_PROMPT = """You are running unattended in the Telegram Digest folder to write a digest. Nobody can answer questions.

Follow HOW-TO-DIGEST.md in this folder exactly, with these specifics:
- Messages were fetched just now, so don't create the fetch-now file.
- Cover the period from {start} to {end}. Use exactly these as "from" and "to".
- Apply what-matters.md. You may fold lines from its "Feedback from the digest" section into rules, as HOW-TO-DIGEST.md describes.
- If there are no new messages in the period, write nothing and reply "Nothing new."
- Otherwise write exactly one digest file in digests/ as described, then reply with one short line saying what you wrote.
- In the digest file, each "text" is plain prose: no links, no [↗] marks and no message numbers (the sources go only in "refs"), and no labels like "Needs attention —" (the app adds the headings). Write people's names as they appear in the messages.
- Only read exports/, .state.json, what-matters.md, HOW-TO-DIGEST.md and digests/. Only write in digests/ and what-matters.md."""


def model_flags(kind, st):
    """Optional model and effort choices; empty means the tool's own default."""
    if kind == "claude":
        m, e = st.get("claude_model"), st.get("claude_effort")
        return (["--model", m] if m else []) + (["--effort", e] if e else [])
    m, e = st.get("codex_model"), st.get("codex_effort")
    return (["-m", m] if m else []) + (["-c", f'model_reasoning_effort="{e}"'] if e else [])


OLD_TOOL = re.compile(r"unknown option|unrecognized|unexpected argument|unknown argument", re.I)


def photos_in(start, end):
    """The photos a digest of this period should look at (newest PHOTO_CAP), with who posted them."""
    with_photo = [r for r in core.read_messages(start, end) if r.get("photo")]
    return with_photo[-PHOTO_CAP:]


def photo_block(recs, attached):
    lines = []
    for r in recs:
        where = r["group"] + (f" › {r['topic']}" if r.get("topic") else "")
        caption = (r.get("text") or "").replace("\n", " ")[:80]
        lines.append(f"  {r['photo']}: message #{r['id']} in {where}, by {r['sender']} at {r['date'][11:16]}"
                     + (f', caption "{caption}"' if caption else ""))
    how = ("They are also attached to this message, in this order." if attached
           else "Open each file with your file-reading tool; they are images.")
    return ("\n- Photos: these messages in the period have a photo saved in this folder. " + how +
            " Use what a photo shows where it matters: dates, times, places, prices, names, what a poster or"
            " screenshot says. Work it into the point it belongs to (for example: the poster says the sauna opens"
            " Friday at 18:00) and cite that message as usual. Skip photos that add nothing, like selfies or memes.\n"
            + "\n".join(lines))


def run_engine(kind, path, start, end):
    prompt = DIGEST_PROMPT.format(start=start.isoformat(timespec="seconds"), end=end.isoformat(timespec="seconds"))
    st = load_settings()
    photos = photos_in(start, end) if st.get("digest_photos") else []
    images = [r["photo"] for r in photos] if kind == "codex" else []
    if photos:
        prompt += photo_block(photos, attached=bool(images))
    extra = model_flags(kind, st)
    code, out, err = _run_engine(kind, path, prompt, extra, images)
    if code != 0 and extra and OLD_TOOL.search(err + out):
        # an older Claude Code / Codex that doesn't know these options: run with its defaults
        code, out, err = _run_engine(kind, path, prompt, [], images)
        if code == 0:
            out += f"\n(Your {ENGINE_NAMES[kind]} is too old for the chosen model or effort, so it used its defaults. Updating it fixes this.)"
    return code, out, err


def _run_engine(kind, path, prompt, extra, images=()):
    via_stdin = WINDOWS and path.lower().endswith((".cmd", ".bat"))
    if kind == "claude":
        cmd = [path, "-p"] + ([] if via_stdin else [prompt]) + ["--permission-mode", "acceptEdits",
               "--allowedTools", "Read,Write,Edit,Glob,Grep", "--output-format", "text"] + extra
    else:
        attach = [f"--image={p}" for p in images] + ["--"] if images else []   # "--": the prompt is never read as an image
        cmd = [path, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--color", "never"] + extra + attach + ["-" if via_stdin else prompt]
    env = dict(os.environ, PATH=tool_path())
    env.pop("ANTHROPIC_API_KEY", None)   # use the person's subscription, not a pay-as-you-go key
    env.pop("OPENAI_API_KEY", None)
    (core.ROOT / "logs").mkdir(exist_ok=True)
    try:
        r = subprocess.run(cmd, cwd=str(core.ROOT), env=env, capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                           input=prompt if via_stdin else None, stdin=None if via_stdin else subprocess.DEVNULL)
        out, err, code = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "Timed out after 15 minutes.", -1
    except Exception as e:
        out, err, code = "", str(e), -1
    with (core.ROOT / "logs" / "digest.log").open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} {ENGINE_NAMES[kind]} {' '.join(extra)} exit {code}\n{out[-4000:]}\n{err[-4000:]}\n")
    return code, out, err


def last_line(*texts):
    for t in texts:
        lines = [x.strip() for x in (t or "").splitlines() if x.strip()]
        if lines:
            return lines[-1][:300]
    return ""


# ---------- digests to the person's phone through their own Telegram bot ----------

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()
BOT_LINK = {}   # pending link: {"code": ..., "username": ...}


def bot_call(token, method, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in params.items()}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            res = json.loads(e.read())
        except Exception:
            res = {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        raise UserError(f"Couldn't reach Telegram: {e}")
    if not res.get("ok"):
        desc = res.get("description") or "Telegram didn't accept that."
        if "Unauthorized" in desc or "Not Found" in desc:
            desc = "Telegram doesn't recognise that token. Copy it again from BotFather's message."
        raise UserError(desc)
    return res["result"]


def bot_config():
    cfg = core.load_env()
    return cfg.get("BOT_TOKEN"), cfg.get("BOT_CHAT_ID"), cfg.get("BOT_USERNAME")


def digest_to_telegram(d):
    """Format a digest as one or more Telegram HTML messages."""
    try:
        start = dt.datetime.fromisoformat(d["from"])
        end = dt.datetime.fromisoformat(d["to"])
    except Exception:
        start = end = None
    msgs = {}
    if start:
        for m in core.read_messages(start - dt.timedelta(days=1), end + dt.timedelta(minutes=1)):
            msgs[(str(m["group_id"]), m["id"])] = m
    h = lambda t: html.escape(str(t), quote=False)
    rich = lambda t: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h(t))

    def refs(gid, ids):
        parts, last = [], None
        for i in ids or []:
            m = msgs.get((str(gid), i))
            if m:
                who = m["sender"].split()[0] if m["sender"] else "?"
                label = (who + " " if m["sender"] != last else "") + m["date"][11:16]
                last, link = m["sender"], m["link"]
            else:
                label, link = f"#{i}", f"https://t.me/c/{str(gid).replace('-100', '', 1)}/{i}"
            parts.append(f'<a href="{html.escape(link)}">{h(label)}</a>')
        return ("  " + ", ".join(parts)) if parts else ""

    when = ""
    if start:
        f, t = start.astimezone(), end.astimezone()
        when = (f"{f:%a %H:%M}–{t:%H:%M}" if f.date() == t.date() else f"{f:%a %H:%M} to {t:%a %H:%M}")
    blocks = [f"<b>{h(d.get('title') or 'Telegram digest')}</b>\n{h(when)}"]
    groups = d.get("groups") or []
    for g in groups:
        gid = g.get("group_id")
        if len(groups) > 1:
            blocks.append(f"<b><u>{h(g.get('title') or '')}</u></b>")
        if g.get("highlights"):
            blocks.append("<b>Needs attention</b>\n" + "\n".join(f"• {rich(b.get('text', ''))}{refs(gid, b.get('refs'))}" for b in g["highlights"]))
        for tp in g.get("topics") or []:
            if tp.get("bullets"):
                blocks.append(f"<b>{h(tp.get('topic') or '')}</b>\n" + "\n".join(f"• {rich(b.get('text', ''))}{refs(gid, b.get('refs'))}" for b in tp["bullets"]))
    chunks, cur = [], ""
    for b in blocks:
        if len(b) > 3800:
            b = b[:3790] + "…"
        if cur and len(cur) + len(b) + 2 > 3900:
            chunks.append(cur)
            cur = b
        else:
            cur = cur + "\n\n" + b if cur else b
    if cur:
        chunks.append(cur)
    return chunks


def send_digest_to_phone(d, force=False):
    token, chat, _ = bot_config()
    if not (token and chat):
        return False
    if not force and not phone_wants(d, load_settings()):
        return False
    for text in digest_to_telegram(d):
        bot_call(token, "sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview="true")
    return True


def phone_wants(d, st):
    policy = st.get("phone_send", "all")
    has_att = any(g.get("highlights") for g in d.get("groups") or [])
    return policy == "all" or (policy == "attention" and has_att)


def send_digest_in_background(d, st):
    if not phone_wants(d, st):    # decided here, so the thread never re-reads settings
        return
    def run():
        try:
            send_digest_to_phone(d, force=True)
        except Exception:
            log(traceback.format_exc())
    threading.Thread(target=run, daemon=True).start()


class Telegram:
    """Owns the one Telegram connection, on its own asyncio thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.phone = None
        self.me = None
        self.exporting = False
        self.digesting = False
        self.code_stamp = code_stamp()
        self.digest_phase = None
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
            "background": os.environ.get("TGD_BACKGROUND") == "1" or os.environ.get("XPC_SERVICE_NAME", "") in SERVICE_LABELS
                          or (not WINDOWS and os.getppid() == 1),
            "os": OS_NAME,
            "exporting": self.exporting, "api": API_VERSION,
            "last_result": self.last_result, "last_error": self.last_error,
        }
        st_ = load_settings()
        kind, _ = pick_engine(st_)
        ds = load_dstate()
        token, chat, uname = bot_config()
        out["bot"] = {"connected": bool(token and chat), "username": uname, "pending": bool(token and not chat),
                      "policy": st_["phone_send"]}
        out["digest"] = {
            "mode": st_["digest_mode"], "engine": kind, "engine_name": ENGINE_NAMES.get(kind),
            "found": {k: bool(v) for k, v in find_engines().items()},
            "running": self.digesting, "phase": self.digest_phase, "last_run": ds.get("last_run"), "last_ok": ds.get("last_ok"),
            "last_message": ds.get("last_message"),
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
            self.last_result = await core.export(c, rebuild_days=rebuild_days,
                                                 photos=bool(load_settings().get("digest_photos")))
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

    async def run_digest(self, auto=False, period=None):
        if self.digesting:
            return {"busy": True}
        self.digesting = True
        ds = load_dstate()
        try:
            last = core.last_export_time()
            if last is None or (dt.datetime.now(dt.timezone.utc) - last).total_seconds() > 300:
                try:
                    await self.export()
                except Exception:
                    pass   # write the digest from what's there
            st = load_settings()
            kind, path = pick_engine(st)
            now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            ds["last_run"] = now_iso
            if auto:
                ds["last_auto_run"] = now_iso
            if not kind:
                ds.update(last_ok=False, last_message="No AI tool found. Install Claude Code or Codex and sign in once.")
                return {"error": ds["last_message"]}
            start, end = digest_period(st, period)
            # make sure the whole period is saved; fetch older messages if it isn't
            tolerance = dt.timedelta(minutes=5)
            cov = core.coverage_start()
            if cov is None or start < cov - tolerance:
                self.digest_phase = "backfill"
                days = min(31.0, (dt.datetime.now(dt.timezone.utc) - start).total_seconds() / 86400 + 0.02)
                while self.exporting:
                    await asyncio.sleep(1)
                try:
                    await self.export(rebuild_days=days)
                except Exception:
                    pass
                cov = core.coverage_start()
            note = ""
            if cov is not None and start < cov - tolerance:   # still missing: only claim what we have
                start = cov
                note = f" Older messages weren't available, so it covers from {start:%a %H:%M}."
            self.digest_phase = "writing"
            if not core.read_messages(start, end):
                ds.update(last_ok=True, last_message="No messages in that period." if period and period != "since_last"
                          else "Nothing new since the last digest.")
                return {"ok": True, "message": ds["last_message"]}
            before = {n for n, _ in _read_digests()}
            code, out, err = await asyncio.to_thread(run_engine, kind, path, start, end)
            new = [(n, d) for n, d in _read_digests() if n not in before]
            if new:
                ds.update(last_ok=True, last_message=f"{ENGINE_NAMES[kind]} wrote “{new[0][1].get('title') or new[0][0]}”.{note}")
                ds.pop("retry_after", None)
                check_new_digests()
            elif code == 0:
                ds.update(last_ok=True, last_message=(last_line(out) or "Finished without writing a digest.") + note)
            else:
                ds.update(last_ok=False, last_message=f"{ENGINE_NAMES[kind]} failed: {last_line(err, out) or 'no details'}. Is it signed in?")
                if auto:
                    ds["retry_after"] = time.time() + 3600
            return {"ok": ds["last_ok"], "message": ds["last_message"]}
        finally:
            save_dstate(ds)
            self.digesting = False
            self.digest_phase = None

    async def _maybe_auto_digest(self, fetched_new):
        st = load_settings()
        if st["digest_mode"] != "auto" or self.digesting or not pick_engine(st)[0]:
            return
        ds = load_dstate()
        if time.time() < ds.get("retry_after", 0):
            return
        now = dt.datetime.now().astimezone()
        last = ds.get("last_auto_run")
        last = dt.datetime.fromisoformat(last) if last else None
        sched = st["digest_schedule"]
        if sched == "after_fetch":
            due = fetched_new
        elif sched == "every":
            due = last is None or now - last >= dt.timedelta(hours=int(st["digest_every_hours"]))
        else:
            hh, mm = (int(x) for x in str(st["digest_daily_at"]).split(":"))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            due = now >= target and (last is None or last < target)
        if not due:
            return
        start, end = digest_period(st)
        if len(core.read_messages(start, end)) < int(st["digest_min_new"]):
            if sched == "daily":   # skip today
                ds["last_auto_run"] = now.isoformat(timespec="seconds")
                save_dstate(ds)
            return
        await self.run_digest(auto=True)

    async def _restart_if_updated(self):
        """After an update replaces the program files, restart into the new version by itself."""
        if code_stamp() == self.code_stamp or self.digesting or self.exporting:
            return
        if WINDOWS and os.environ.get("TGD_BACKGROUND") != "1":
            return      # started by hand on Windows: nothing would start it again
        log("Program files were updated; restarting to use the new version.")
        try:
            if self.client is not None:
                await self.client.disconnect()
        except Exception:
            pass
        for stream in (sys.stdout, sys.stderr):
            if stream:
                stream.flush()
        if WINDOWS:
            os._exit(75)    # the background runner (service.pyw) starts it again straight away
        os.execv(sys.executable, [sys.executable, CODE_FILES[0]] + sys.argv[1:])

    async def _scheduler(self):
        await asyncio.sleep(15)
        retry_at = 0.0
        while True:
            try:
                await self._restart_if_updated()
                check_new_digests()
                requested = FETCH_REQUEST.exists()
                last = core.last_export_time()
                due = requested or last is None or core.load_state().get("needs_rebuild") or \
                    (dt.datetime.now(dt.timezone.utc) - last).total_seconds() >= fetch_every_s()
                fetched_new = False
                if due and time.time() >= retry_at and core.has_keys() and core.load_selection()["groups"]:
                    c = await self._client()
                    if await c.is_user_authorized():
                        if requested:
                            FETCH_REQUEST.unlink()
                        try:
                            res = await self.export()
                            fetched_new = bool(res and res.get("total"))
                        except Exception:
                            retry_at = time.time() + 300  # back off after a failure
                await self._maybe_auto_digest(fetched_new)
            except Exception:
                log(traceback.format_exc())
            await asyncio.sleep(30)  # wall-clock checks, so it catches up after sleep


class UserError(Exception):
    pass


TG = None


MD_LINK = re.compile(r"\s*\[([^\]]*)\]\(((?:https?|tg)://[^)\s]+)\)")
ATT_LABEL = re.compile(r"^\s*\**\s*needs attention\s*\**\s*[\u2014\u2013:\-]+\s*", re.I)


def clean_point(p):
    """Tidy a digest point an AI wrote in chat style: links in the text become sources, labels go."""
    if not isinstance(p, dict):
        return p
    text, refs = str(p.get("text") or ""), []
    for r in p.get("refs") or []:
        try:
            refs.append(int(r))
        except (TypeError, ValueError):
            pass
    def link(mo):
        label, url = mo.group(1).strip(), mo.group(2)
        mid = re.search(r"[?&]post=(\d+)", url) or re.search(r"/(\d+)/?(?:[?#].*)?$", url)
        if mid and int(mid.group(1)) not in refs:
            refs.append(int(mid.group(1)))
        keep = re.search(r"[^\W\d_]", label) and label.lower() not in ("link", "source", "src", "here")
        return (" " + label) if keep else ""
    text = MD_LINK.sub(link, text)
    if ATT_LABEL.match(text):
        text = ATT_LABEL.sub("", text)
        text = text[:1].upper() + text[1:]
    text = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return {**p, "text": text, "refs": refs}


def load_digest(f):
    d = json.loads(f.read_text(encoding="utf-8"))
    for g in d.get("groups") or []:
        g["highlights"] = [clean_point(x) for x in g.get("highlights") or []]
        for t in g.get("topics") or []:
            t["bullets"] = [clean_point(x) for x in t.get("bullets") or []]
    return d


def _read_digests():
    out = []
    if DIGESTS.is_dir():
        for f in DIGESTS.glob("*.json"):
            try:
                out.append((f.stem, load_digest(f)))
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
    if known:   # don't send digests that existed before the first check
        send_digest_in_background(fresh[0][1], st)
    if known and st.get("notify") != "off":
        name, d = fresh[0]
        att = [h.get("text", "") for g in d.get("groups") or [] for h in (g.get("highlights") or [])]
        if att or st.get("notify") == "all":
            text = (f"{len(att)} need attention: " + re.sub(r"\*\*", "", att[0])) if att else "Nothing urgent."
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
        mp = re.fullmatch(r"/media/(-?\d+)/(\d+)\.jpg", p)
        if mp:
            f = core.ROOT / core.photo_rel(mp.group(1), mp.group(2))
            if not f.is_file():
                return self._send(404, {"error": "not found"})
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "private, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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
            "/api/export": lambda: TG.call(TG.export(self._days(body.get("rebuild_days")))),
            "/api/preferences": lambda: self._save_prefs(body),
            "/api/feedback": lambda: self._feedback(body),
            "/api/settings": lambda: self._save_settings(body),
            "/api/seen": lambda: self._seen(body),
            "/api/digest/run": lambda: self._run_digest(body),
            "/api/bot/token": lambda: self._bot_token(body),
            "/api/bot/check": lambda: self._bot_check(),
            "/api/bot/test": lambda: self._bot_test(),
            "/api/bot/latest": lambda: self._bot_latest(),
            "/api/bot/disconnect": lambda: self._bot_disconnect(),
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

    def _bot_token(self, body):
        token = re.sub(r"\s+", "", str(body.get("token", "")))
        if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
            raise UserError("That doesn't look like a bot token. It looks like 123456789:AAH… and is in BotFather's message after you create the bot.")
        me = bot_call(token, "getMe")
        core.update_env({"BOT_TOKEN": token, "BOT_USERNAME": me.get("username"), "BOT_CHAT_ID": None})
        BOT_LINK.update(code=secrets.token_urlsafe(9).replace("-", "x").replace("_", "y"), username=me.get("username"))
        return {"username": me.get("username"), "link": f"https://t.me/{me.get('username')}?start={BOT_LINK['code']}"}

    def _bot_link(self):
        token, chat, uname = bot_config()
        if not token:
            raise UserError("Paste your bot's token first.")
        if not BOT_LINK.get("code"):
            BOT_LINK.update(code=secrets.token_urlsafe(9).replace("-", "x").replace("_", "y"), username=uname)
        return token

    def _bot_check(self):
        token = self._bot_link()
        updates = bot_call(token, "getUpdates", timeout=0, allowed_updates=["message"])
        found, last = None, None
        for u in updates:
            last = u["update_id"]
            m = u.get("message") or {}
            if m.get("chat", {}).get("type") == "private" and (m.get("text") or "").strip() == f"/start {BOT_LINK['code']}":
                found = m
        if last is not None:
            bot_call(token, "getUpdates", offset=last + 1, timeout=0)   # mark them as read
        if not found:
            return {"connected": False, "link": f"https://t.me/{BOT_LINK['username']}?start={BOT_LINK['code']}"}
        core.update_env({"BOT_CHAT_ID": str(found["chat"]["id"])})
        BOT_LINK.clear()
        name = (found.get("from") or {}).get("first_name") or "there"
        bot_call(token, "sendMessage", chat_id=found["chat"]["id"],
                 text=f"Hi {name}! This is your Telegram digest. New digests will arrive here, with links straight to the original messages.")
        return {"connected": True}

    def _bot_test(self):
        token, chat, _ = bot_config()
        if not (token and chat):
            raise UserError("Connect your bot first.")
        bot_call(token, "sendMessage", chat_id=chat, text="Test from your Telegram digest: it works.")
        return {"ok": True}

    def _bot_latest(self):
        items = _read_digests()
        if not items:
            raise UserError("There's no digest yet.")
        if not send_digest_to_phone(items[0][1], force=True):
            raise UserError("Connect your bot first.")
        return {"ok": True}

    def _bot_disconnect(self):
        core.update_env({"BOT_TOKEN": None, "BOT_CHAT_ID": None, "BOT_USERNAME": None})
        BOT_LINK.clear()
        return {"ok": True}

    def _days(self, v):
        if v in (None, "", 0):
            return None
        v = float(v)
        if not 0 < v <= 31:
            raise UserError("You can get up to 31 days of older messages.")
        return v

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
        for key, value in body.items():
            if key in CHOICES:
                if isinstance(CHOICES[key][0], int):
                    value = int(value)
                if value not in CHOICES[key]:
                    raise UserError(f"Pick one of the offered options for {key}.")
                st[key] = value
            elif key in ("onboarded", "digests_chosen"):
                st[key] = bool(value)
            elif key == "digest_photos":
                on = value in (True, 1, "1", "true", "on")
                if on and not st.get("digest_photos"):
                    core.PHOTO_BACKFILL.touch()      # fetch photos for the last few days too
                st[key] = on
            elif key == "codex_model":
                value = str(value).strip()
                if not re.fullmatch(r"[A-Za-z0-9._:/-]{0,60}", value):
                    raise UserError("That doesn't look like a model name.")
                st[key] = value
            elif key == "digest_daily_at":
                if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
                    raise UserError("Use a time like 08:00.")
                st[key] = value
        save_settings(st)
        return st

    def _run_digest(self, body):
        period = body.get("period") or None
        if period is not None and period not in PERIODS:
            raise UserError("Unknown period.")
        if TG.digesting:
            return {"busy": True}
        TG.submit(TG.run_digest(period=period))
        return {"started": True}

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
        return load_digest(f)

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
