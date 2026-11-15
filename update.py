"""Checks GitHub for a newer published version of Telegram Digest, and installs it when asked.

A version counts as published when release.json on GitHub has a higher "version" than the
copy here; ordinary pushes without a version bump don't reach anyone. Installing downloads
that version as one zip, checks the new code compiles, installs any missing package, then
swaps the files in. Settings, the Telegram login and saved messages are never touched.
"""
import importlib.util
import io
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "m3h0w/telegram-digest"
RELEASE_URL = f"https://raw.githubusercontent.com/{REPO}/main/release.json"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")
NEVER = {".env", "settings.json", "selection.json", ".state.json", ".digest-state.json", "what-matters.md"}
CODE = {"app.py", "export.py", "update.py", "service.pyw"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def local_release():
    try:
        return json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    except Exception:
        return {"version": "0"}


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))) or (0,)


def newer(a, b):
    return version_tuple(a) > version_tuple(b)


def is_git_checkout():
    return (ROOT / ".git").exists()


def _get(url, ctx, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "telegram-digest-updater"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("The download was larger than expected.")
    return data


def check(ctx):
    """What GitHub offers compared with this copy."""
    remote = json.loads(_get(f"{RELEASE_URL}?t={int(time.time() // 300)}", ctx, 200_000))
    current = local_release().get("version", "0")
    latest = str(remote.get("version") or "0")
    return {"current": current, "latest": latest, "available": newer(latest, current),
            "notes": str(remote.get("notes") or "")[:600], "reinstall": bool(remote.get("reinstall")),
            "checked": time.time()}


def _replace(src, dst):
    for attempt in range(20):
        try:
            os.replace(src, dst)
            return
        except PermissionError:     # Windows: a file being read this instant
            if attempt == 19:
                raise
            time.sleep(0.05)


def apply(ctx):
    """Download and install the published version. Returns what happened."""
    if is_git_checkout():
        raise RuntimeError("This copy is a git checkout. Update it with git instead.")
    z = zipfile.ZipFile(io.BytesIO(_get(ZIP_URL, ctx, 20 * 1024 * 1024)))
    top = z.namelist()[0].split("/")[0]
    read = lambda name: z.read(f"{top}/{name}")
    rel = json.loads(read("release.json"))
    current = local_release().get("version", "0")
    if not newer(rel.get("version"), current):
        return {"updated": False, "version": current}
    wanted = [f for f in rel.get("files", []) if isinstance(f, str) and SAFE_NAME.fullmatch(f) and f not in NEVER]
    stage = Path(tempfile.mkdtemp(prefix=".update-", dir=ROOT))     # same disk, so the swap is a rename
    try:
        staged = []
        for f in dict.fromkeys(wanted + ["release.json"]):
            try:
                (stage / f).write_bytes(read(f))
                staged.append(f)
            except KeyError:
                pass
        for f in staged:            # never install code that doesn't even compile
            if f.endswith((".py", ".pyw")):
                py_compile.compile(str(stage / f), cfile=str(stage / (f + ".check")), doraise=True)
        for pkg in rel.get("requirements", []):
            if isinstance(pkg, str) and SAFE_NAME.fullmatch(pkg) and importlib.util.find_spec(pkg) is None:
                subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", pkg],
                               check=True, timeout=600, capture_output=True, creationflags=NO_WINDOW)
        changed = [f for f in staged if not (ROOT / f).exists() or (ROOT / f).read_bytes() != (stage / f).read_bytes()]
        # page and documents first, program files next, the version marker last
        for f in sorted(changed, key=lambda f: (f == "release.json", f in CODE)):
            _replace(stage / f, ROOT / f)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"updated": True, "version": str(rel.get("version")), "reinstall": bool(rel.get("reinstall")),
            "code_changed": any(f in CODE for f in changed)}
