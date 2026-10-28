"""Play online for free: a Cloudflare "quick tunnel".

cloudflared (a free program from Cloudflare) makes an outgoing connection and
gets a random https://….trycloudflare.com address that leads back to this app.
No account, no domain, no open ports on the router. The address changes every
time the tunnel starts.

Requests that arrive through the tunnel carry Cloudflare's headers, so they are
never treated as the DM (see auth.is_local_request); friends join with the
campaign's join code like they would on Wi-Fi.
"""
import atexit
import os
import re
import shutil
import subprocess
import threading
import time

from flask import Blueprint, current_app, jsonify

from . import fields as F
from .auth import is_dm

bp = Blueprint("online", __name__, url_prefix="/api")

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
INSTALL_HINT = "winget install --id Cloudflare.cloudflared"
_lock = threading.Lock()
_state = {"proc": None, "url": None, "error": None, "started": None, "lines": []}


def find_cloudflared():
    """cloudflared on PATH, or where the Windows installer / winget puts it."""
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "cloudflared", "cloudflared.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "cloudflared", "cloudflared.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "cloudflared.exe"),
        os.path.join(current_app.config.get("DATA_DIR", ""), "cloudflared.exe"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def _running():
    p = _state["proc"]
    return p is not None and p.poll() is None


def _read(proc):
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if not line:
            continue
        with _lock:
            _state["lines"] = (_state["lines"] + [line])[-40:]
            m = URL_RE.search(line)
            if m and not _state["url"]:
                _state["url"] = m.group(0)
            if "failed" in line.lower() and "error" in line.lower() and not _state["url"]:
                _state["error"] = line[-300:]
    with _lock:
        if _state["proc"] is proc and not _state["url"] and not _state["error"]:
            _state["error"] = "The tunnel stopped before it got an address. Check your internet connection and try again."


METRICS_PORTS = range(20241, 20246)  # where cloudflared answers questions about itself, on this computer only
_seen = {"at": 0.0, "found": None}


def left_running():
    """A tunnel this app started before it was restarted keeps running (and its link keeps
    working): find it, so the Players page shows that same link instead of making a new one.
    (url, metrics port) or None. Checked at most every 10 seconds."""
    import json
    import urllib.request
    if time.time() - _seen["at"] < 10:
        return _seen["found"]
    found = None
    for port in METRICS_PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/quicktunnel", timeout=0.5) as r:
                host = json.load(r).get("hostname")
            if host:
                found = (f"https://{host}", port)
                break
        except Exception:
            continue
    _seen.update(at=time.time(), found=found)
    return found


def status():
    with _lock:
        running = _running()
        out = {
            "installed": bool(find_cloudflared()),
            "install_hint": INSTALL_HINT,
            "running": running,
            "url": _state["url"] if running else None,
            "error": _state["error"],
            "started": _state["started"] if running else None,
        }
    if not running:
        old = left_running()
        if old:
            out.update(running=True, url=old[0], error=None, kept=True)
    return out


def stop():
    with _lock:
        p = _state["proc"]
        _state.update(proc=None, url=None, started=None)
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def stop_left_running():
    """Stop a tunnel kept from before a restart: the cloudflared listening on its metrics port."""
    old = left_running()
    if not old or os.name != "nt":
        return
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    for line in out.splitlines():
        bits = line.split()
        if len(bits) >= 5 and bits[1] == f"127.0.0.1:{old[1]}" and bits[3] == "LISTENING":
            subprocess.run(["taskkill", "/PID", bits[4], "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _seen.update(at=0.0, found=None)


atexit.register(stop)


def _dm_only():
    if not is_dm():
        raise F.ApiError("Only the DM can do that.", status=403)


@bp.get("/online")
def api_status():
    _dm_only()
    return jsonify(status())


@bp.post("/online/start")
def api_start():
    _dm_only()
    exe = find_cloudflared()
    if not exe:
        raise F.ApiError("cloudflared isn't installed yet. Open PowerShell and run: " + INSTALL_HINT + " — then try again.")
    if not _running() and left_running():  # still up from before a restart: same link
        return jsonify(status() | {"already": True})
    with _lock:
        if _running():
            return jsonify(status() | {"already": True})
        port = current_app.config.get("PORT", 5050)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", creationflags=flags)
        _state.update(proc=proc, url=None, error=None, started=time.time(), lines=[])
    threading.Thread(target=_read, args=(proc,), daemon=True).start()
    # Usually the address shows up within a few seconds; the page keeps asking after this.
    for _ in range(40):
        with _lock:
            if _state["url"] or _state["error"] or proc.poll() is not None:
                break
        time.sleep(0.25)
    return jsonify(status())


@bp.post("/online/stop")
def api_stop():
    _dm_only()
    stop()
    stop_left_running()
    return jsonify(status())
