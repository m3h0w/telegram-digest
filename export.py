#!/usr/bin/env python3
"""Read-only Telegram exporter (library + CLI).

Saves new messages from the selected groups / topics to

  exports/YYYY-MM-DD/<group>/messages.jsonl   one JSON object per message (with Telegram links)
  exports/YYYY-MM-DD/<group>/<topic>.md       human-readable, one file per topic ("chat.md" for plain groups)

It only ever reads: it never sends anything and never marks messages as read.

Normally app.py (the local web app) runs exports for you. The CLI is for debugging,
and must not run while the app is running (they share the login session):

  python export.py               export new messages
  python export.py --rebuild 1   re-fetch the last day (duplicates are skipped)
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import time
import re
import sys
from pathlib import Path

from telethon import TelegramClient, functions, types
from telethon.utils import get_display_name, get_peer_id

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"
SELECTION = ROOT / "selection.json"
LEGACY_GROUPS = ROOT / "groups.txt"
STATE = ROOT / ".state.json"
EXPORTS = ROOT / "exports"
MEDIA = ROOT / "media"                       # photo previews: media/<group id>/<message id>.jpg
PHOTO_BACKFILL = ROOT / ".photos-backfill"   # present = also fetch photos for recently saved messages
PHOTO_KEEP_DAYS = 30
# The login session is a full key to the account, so it lives outside the repo,
# readable only by you.
SECRET_DIR = Path.home() / ".config" / "telegram-digest"
SESSION = SECRET_DIR / "digest"  # Telethon adds ".session"
SESSION_FILE = Path(str(SESSION) + ".session")


WINDOWS = os.name == "nt"
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def write_atomic(path, text):
    """Write a file so readers never see it half-written."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows: someone is reading the file this instant
            if not WINDOWS or attempt == 19:
                raise
            time.sleep(0.05)


def log(msg):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# ---------- config ----------

def load_env():
    cfg = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def save_env(api_id, api_hash):
    new = {"API_ID": str(api_id).strip(), "API_HASH": str(api_hash).strip()}
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in new:
            line = f"{key}={new.pop(key)}"
        out.append(line)
    out += [f"{k}={v}" for k, v in new.items()]
    old = os.umask(0o077)
    try:
        ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    finally:
        os.umask(old)
    os.chmod(ENV, 0o600)


def update_env(updates):
    """Set (or, with None, remove) keys in .env, keeping everything else."""
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, done = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            done.add(key)
            if updates[key] is None:
                continue
            line = f"{key}={updates[key]}"
        out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in done and v is not None]
    old = os.umask(0o077)
    try:
        ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    finally:
        os.umask(old)
    os.chmod(ENV, 0o600)


def has_keys(cfg=None):
    cfg = cfg or load_env()
    return bool(cfg.get("API_ID") and cfg.get("API_HASH"))


def make_client(cfg):
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_DIR, 0o700)
    return TelegramClient(
        str(SESSION), int(cfg["API_ID"]), cfg["API_HASH"],
        device_model="telegram-digest (Windows)" if WINDOWS else "telegram-digest (Mac)", app_version="2.0",
        receive_updates=False,
    )


def secure_session():
    if SESSION_FILE.exists():
        os.chmod(SESSION_FILE, 0o600)


# ---------- selection: which groups and which topics ----------
# {"groups": {"-100123": {"title": "...", "forum": true, "topics": "all" | [1, 5, 9]}}}

def load_selection():
    if SELECTION.exists():
        sel = json.loads(SELECTION.read_text(encoding="utf-8"))
        sel.setdefault("groups", {})
        return sel
    sel = {"groups": {}}
    if LEGACY_GROUPS.exists():  # migrate from the first version
        for line in LEGACY_GROUPS.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(-?\d+)\s*(?:#\s*(.*))?$", line)
            if m:
                sel["groups"][m.group(1)] = {"title": (m.group(2) or "").strip(), "topics": "all"}
        if sel["groups"]:
            save_selection(sel)
    return sel


def save_selection(sel):
    write_atomic(SELECTION, json.dumps(sel, indent=1, ensure_ascii=False))


# ---------- state ----------

def load_state():
    if not STATE.exists():
        return {"last_ids": {}, "last_export": None, "needs_rebuild": False}
    st = json.loads(STATE.read_text(encoding="utf-8"))
    if "last_ids" not in st:  # first-version format: {"-100…": last_id}
        return {"last_ids": st, "last_export": None, "needs_rebuild": True}
    return st


def save_state(st):
    write_atomic(STATE, json.dumps(st, indent=1))


def last_export_time():
    t = load_state().get("last_export")
    return dt.datetime.fromisoformat(t) if t else None


# ---------- Telegram lookups ----------

async def resolve(client, gid):
    try:
        return await client.get_entity(gid)
    except Exception:
        async for d in client.iter_dialogs():
            if d.id == gid:
                return d.entity
    return None


async def list_groups(client):
    out = []
    async for d in client.iter_dialogs():
        if not (d.is_group or d.is_channel):
            continue
        out.append({
            "id": str(d.id),
            "title": d.name or "",
            "kind": "channel" if (d.is_channel and not d.is_group) else "group",
            "forum": bool(getattr(d.entity, "forum", False)),
        })
    return out


async def forum_topics(client, entity):
    """{topic_id: title} for forum groups, {} for plain groups."""
    if not getattr(entity, "forum", False):
        return {}
    topics = {1: "General"}
    offset_date, offset_id, offset_topic = None, 0, 0
    try:
        for _ in range(10):  # up to 1000 topics
            res = await client(functions.messages.GetForumTopicsRequest(
                peer=entity, offset_date=offset_date, offset_id=offset_id,
                offset_topic=offset_topic, limit=100))
            got = [t for t in res.topics if getattr(t, "title", None)]
            for t in got:
                topics[t.id] = t.title
            if len(res.topics) < 100 or not got:
                break
            last = got[-1]
            offset_topic, offset_id = last.id, last.top_message
            offset_date = getattr(last, "date", None)
    except Exception as e:  # topic names are a nice-to-have
        log(f"  (couldn't load topic names: {e})")
    return topics


async def list_topics(client, gid):
    entity = await resolve(client, int(gid))
    if entity is None:
        return []
    return [{"id": tid, "title": title} for tid, title in (await forum_topics(client, entity)).items()]


# ---------- records ----------

def media_label(m):
    if m.sticker:
        return "[sticker]"
    if m.voice:
        return "[voice message]"
    if m.video_note:
        return "[video message]"
    if m.gif:
        return "[gif]"
    if m.video:
        return "[video]"
    if m.audio:
        return "[audio]"
    if m.photo:
        return "[photo]"
    if m.poll:
        p = m.poll.poll
        q = getattr(p.question, "text", p.question)
        opts = " / ".join(str(getattr(a.text, "text", a.text)) for a in p.answers)
        return f"[poll: {q} — {opts}]"
    if m.venue or m.geo:
        return "[location]"
    if m.contact:
        return "[contact]"
    if m.document:
        name = m.file.name if m.file else None
        return f"[file: {name}]" if name else "[file]"
    if m.web_preview:
        return ""  # the link is already in the text
    return "[media]" if m.media else ""


def topic_id(m):
    r = m.reply_to
    if not r or not getattr(r, "forum_topic", False):
        return 1  # General
    return getattr(r, "reply_to_top_id", None) or r.reply_to_msg_id


def links(entity, msg_id, tid):
    """(web link, Telegram-app link) for one message."""
    uname = getattr(entity, "username", None)
    thread = tid if tid and tid != 1 else None
    if uname:
        web = f"https://t.me/{uname}/" + (f"{thread}/" if thread else "") + str(msg_id)
        app = f"tg://resolve?domain={uname}&post={msg_id}" + (f"&thread={thread}" if thread else "")
    else:
        web = f"https://t.me/c/{entity.id}/" + (f"{thread}/" if thread else "") + str(msg_id)
        app = f"tg://privatepost?channel={entity.id}&post={msg_id}" + (f"&thread={thread}" if thread else "")
    return web, app


def record(m, entity, gid, group_title, topics):
    if isinstance(m, types.MessageService):
        return None  # joins, pins, title changes
    tid = topic_id(m) if topics else 0
    reply = None
    r = m.reply_to
    if r and getattr(r, "reply_to_msg_id", None):
        # in forums, a plain post in a topic "replies" to the topic itself
        if not (getattr(r, "forum_topic", False) and not getattr(r, "reply_to_top_id", None)):
            reply = r.reply_to_msg_id
    s = m.sender
    web, app = links(entity, m.id, tid)
    return {
        "id": m.id,
        "date": m.date.astimezone().isoformat(timespec="seconds"),
        "group_id": gid,
        "group": group_title,
        "topic_id": tid,
        "topic": topics.get(tid, f"topic {tid}") if topics else "",
        "sender": (get_display_name(s) if s else None) or getattr(m, "post_author", None) or "?",
        "text": (m.message or "").strip(),
        "media": media_label(m),
        "reply_to": reply,
        "forwarded": bool(getattr(m, "fwd_from", None)),
        "out": bool(getattr(m, "out", False)),      # written by the person this digest is for
        "link": web,
        "app_link": app,
    }


def slug(s):
    s = re.sub(r"[/&+|]", " ", s or "")
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.U).strip()
    s = re.sub(r"\s+", "-", s).lower()[:60]
    return s + "-" if WINDOWS and s in RESERVED else s    # names Windows won't allow as files


def photo_rel(gid, mid):
    return f"media/{gid}/{mid}.jpg"


def photo_of(r):
    """Path (relative to the folder) of a message's saved photo, or None."""
    if r.get("media") != "[photo]":
        return None
    rel = photo_rel(r["group_id"], r["id"])
    return rel if (ROOT / rel).exists() else None


def _preview_size(photo):
    """The size type of a preview about 800 px across: enough to read a poster, about 100 KB."""
    sizes = sorted((s for s in getattr(photo, "sizes", []) if getattr(s, "w", 0) and getattr(s, "h", 0)),
                   key=lambda s: max(s.w, s.h))
    if not sizes:
        return None
    return next((s for s in sizes if max(s.w, s.h) >= 800), sizes[-1]).type


async def save_photo(client, m, gid):
    path = ROOT / photo_rel(gid, m.id)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.stem + ".part")
    part.unlink(missing_ok=True)          # a leftover from an interrupted download
    got = await client.download_media(m, file=str(part), thumb=_preview_size(m.photo))
    if not got or not os.path.exists(got):
        return False
    os.replace(got, path)                 # use the path Telegram's library actually wrote
    return True


def prune_photos(days=PHOTO_KEEP_DAYS):
    if not MEDIA.exists():
        return
    cutoff = time.time() - days * 86400
    for f in MEDIA.glob("*/*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def md_line(r):
    head = f"[{r['date'][11:16]}] #{r['id']} {r['sender']}"
    if r["reply_to"]:
        head += f" ↪#{r['reply_to']}"
    if r["forwarded"]:
        head += " (forwarded)"
    ph = photo_of(r)
    media = f"[photo: {ph}]" if ph else r["media"]
    body = " ".join(x for x in (media, r["text"]) if x) or "[empty]"
    return f"{head}: " + body.replace("\n", "\n    ")


def write_day(day, group_title, recs):
    folder = EXPORTS / day / (slug(group_title) or "group")
    folder.mkdir(parents=True, exist_ok=True)
    jl = folder / "messages.jsonl"
    seen = set()
    if jl.exists():
        for line in jl.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    new = [r for r in recs if r["id"] not in seen]
    if not new:
        return 0
    with jl.open("a", encoding="utf-8") as fh:
        for r in new:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_topic = {}
    for r in new:
        by_topic.setdefault((r["topic_id"], r["topic"]), []).append(r)
    for (tid, tname), rs in by_topic.items():
        f = folder / f"{(slug(tname) or 'topic-' + str(tid)) if tid else 'chat'}.md"
        fresh = not f.exists()
        with f.open("a", encoding="utf-8") as fh:
            if fresh:
                fh.write(f"# {group_title}" + (f" › {tname}" if tname else "") + f" — {day}\n\n")
            fh.write("\n".join(md_line(r) for r in rs) + "\n")
    return len(new)


async def export(client, rebuild_days=None, days_back=None, photos=False):
    """Fetch new messages for the selected groups/topics (and their photos). Returns a summary dict."""
    sel = load_selection()["groups"]
    st = load_state()
    if days_back is None:
        days_back = float(load_env().get("DAYS_BACK", 1))
    if st.get("needs_rebuild") and rebuild_days is None:
        rebuild_days = days_back  # one-off after upgrading from the first version
    photo_backfill = photos and rebuild_days is None and (PHOTO_BACKFILL.exists() or not MEDIA.exists())
    if photo_backfill:            # photos were just switched on: also get them for the last few days
        rebuild_days = max(float(days_back), 3)
    saved_photos = failed_photos = 0
    now = dt.datetime.now(dt.timezone.utc)
    summary = {"groups": {}, "total": 0}
    for gid_s, g in sel.items():
        entity = await resolve(client, int(gid_s))
        if entity is None:
            log(f"Skipping {g.get('title') or gid_s}: not found (left the group?)")
            continue
        gid = str(get_peer_id(entity))
        title = get_display_name(entity) or g.get("title") or gid
        topics = await forum_topics(client, entity)
        allowed = g.get("topics", "all")
        allowed = None if allowed == "all" else {int(t) for t in allowed}
        last_id = st["last_ids"].get(gid_s)
        kw = {"reverse": True}
        if rebuild_days:
            kw["offset_date"] = now - dt.timedelta(days=float(rebuild_days))
        elif last_id:
            kw["min_id"] = last_id
        else:
            kw["offset_date"] = now - dt.timedelta(days=days_back)
        covers_from = kw.get("offset_date")
        by_day = {}
        async for m in client.iter_messages(entity, **kw):
            last_id = max(last_id or 0, m.id)
            r = record(m, entity, gid, title, topics)
            if r is None or (allowed is not None and r["topic_id"] not in allowed):
                continue
            if photos and m.photo:
                try:
                    saved_photos += await save_photo(client, m, gid)
                except Exception:
                    failed_photos += 1
            by_day.setdefault(r["date"][:10], []).append(r)
        n = sum(write_day(day, title, recs) for day, recs in sorted(by_day.items()))
        if last_id:
            st["last_ids"][gid_s] = last_id
        if covers_from is not None:   # we now hold everything from this moment on
            cov = st.setdefault("covered_from", {})
            old = cov.get(gid_s)
            if old is None or covers_from < dt.datetime.fromisoformat(old):
                cov[gid_s] = covers_from.isoformat(timespec="seconds")
        summary["groups"][title] = n
        summary["total"] += n
        log(f"{title}: {n} new message(s)")
    if photos:
        MEDIA.mkdir(exist_ok=True)
        if photo_backfill:
            PHOTO_BACKFILL.unlink(missing_ok=True)
        prune_photos()
        if saved_photos or failed_photos:
            log(f"photos: {saved_photos} saved" + (f", {failed_photos} couldn't be downloaded" if failed_photos else ""))
    summary["photos"] = saved_photos
    st["last_export"] = now.isoformat(timespec="seconds")
    st["last_count"] = summary["total"]
    st["needs_rebuild"] = False
    save_state(st)
    return summary


# ---------- reading exports (used by the web app) ----------

def _earliest_saved(gid):
    """Date of the oldest saved message for a group (for installs from before coverage was tracked)."""
    for day in reversed(export_dates()):
        for jl in (EXPORTS / day).glob("*/messages.jsonl"):
            for line in jl.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("group_id") == gid:
                    return dt.datetime.fromisoformat(r["date"])
    return None


def coverage_start():
    """From when on we hold every message of every followed group (None if unknown)."""
    sel = load_selection()["groups"]
    if not sel:
        return None
    cov = load_state().get("covered_from", {})
    starts = []
    for gid in sel:
        t = dt.datetime.fromisoformat(cov[gid]) if gid in cov else _earliest_saved(gid)
        if t is None:
            return None
        starts.append(t)
    return max(starts)


def export_dates():
    if not EXPORTS.exists():
        return []
    return sorted((p.name for p in EXPORTS.iterdir()
                   if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)), reverse=True)


def read_messages(start, end):
    """All exported messages with start <= date < end (aware datetimes)."""
    out, seen = [], set()
    day = start.astimezone().date() - dt.timedelta(days=1)
    last = end.astimezone().date() + dt.timedelta(days=1)
    while day <= last:
        folder = EXPORTS / day.isoformat()
        if folder.is_dir():
            for jl in folder.glob("*/messages.jsonl"):
                for line in jl.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    key = (r["group_id"], r["id"])
                    if key in seen:
                        continue
                    t = dt.datetime.fromisoformat(r["date"])
                    if start <= t < end:
                        seen.add(key)
                        out.append(r)
        day += dt.timedelta(days=1)
    out.sort(key=lambda r: r["date"])
    for r in out:
        ph = photo_of(r)
        if ph:
            r["photo"] = ph
    return out


# ---------- CLI ----------

async def _cli(args):
    cfg = load_env()
    if not has_keys(cfg):
        sys.exit("No API keys in .env — open the web app (http://localhost:8765) to set up.")
    client = make_client(cfg)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            sys.exit("Not logged in — open the web app (http://localhost:8765) to log in.")
        await export(client, rebuild_days=args.rebuild)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", type=float, metavar="DAYS", help="re-fetch the last DAYS days")
    asyncio.run(_cli(ap.parse_args()))
