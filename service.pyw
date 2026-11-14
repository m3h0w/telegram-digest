"""Keeps Telegram Digest running in the background on Windows (launchd does this on a Mac).

The installer puts a shortcut to this file in the Startup folder, so it starts when you log
in. It runs with pythonw.exe, so no window appears. It starts app.py, and starts it again if
it stops: straight away after an update, otherwise after a short pause.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = os.environ.get("TGD_PORT", "8765")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UPDATED = 75          # app.py exits with this after its files were updated


def answering():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def python_exe():
    # pythonw.exe has no output streams; run the app with the python.exe next to it, hidden
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


def main():
    if answering():          # already running (for example started twice)
        return
    (ROOT / "logs").mkdir(exist_ok=True)
    env = dict(os.environ, TGD_BACKGROUND="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    quick_stops = 0
    while True:
        started = time.time()
        with open(ROOT / "logs" / "app.log", "a", encoding="utf-8") as log:
            code = subprocess.call([python_exe(), "-X", "utf8", str(ROOT / "app.py")], cwd=str(ROOT), env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=NO_WINDOW)
        if code == UPDATED:
            quick_stops = 0
            continue
        if time.time() - started < 30:
            quick_stops += 1
            if answering():  # another copy has the port; leave it to that one
                return
        else:
            quick_stops = 0
        time.sleep(min(300, 5 * 2 ** min(quick_stops, 6)))


if __name__ == "__main__":
    main()
