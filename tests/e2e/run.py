"""Run browser tests against a COPY of the real data, never the data itself.

    python tests/e2e/run.py e2e_players.py e2e_moves.py --engine all --devices mixed
    python tests/e2e/run.py --all

For each script (and each engine): copy data/dnd_tracker.sqlite3 and data/uploads into a temp
folder, start the app on that copy (port 5077, LAN mode), switch magic-item auras off (prep.py),
run the script, then stop that server. Prints a one-line summary per run.
Run it with the Python that has Playwright installed (see README.md)."""
import argparse
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(os.path.dirname(HERE))
APP_PY = os.path.join(APP_DIR, ".venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(APP_DIR, ".venv", "bin", "python")
# scripts that need something extra on their test server
SERVER_ENV = {"e2e_online_dead.py": {"DND_TUNNEL_PORTS": "20249-20249"}}
# scripts that start their own servers
OWN_SERVER = {"e2e_reload.py"}


def copy_data(dest):
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    src = sqlite3.connect(f"file:{os.path.join(APP_DIR, 'data', 'dnd_tracker.sqlite3')}?mode=ro", uri=True)
    dst = sqlite3.connect(os.path.join(dest, "dnd_tracker.sqlite3"))
    src.backup(dst)
    dst.close(); src.close()
    up = os.path.join(APP_DIR, "data", "uploads")
    if os.path.isdir(up):
        shutil.copytree(up, os.path.join(dest, "uploads"))


def up(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/join/build", timeout=1)
        return True
    except Exception:
        return False


def stop(proc, port):
    """Stop the test server. On Windows the venv's python.exe starts the real Python as a child,
    so also stop whatever still listens on the test port."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        for line in subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout.splitlines():
            bits = line.split()
            if len(bits) >= 5 and bits[1].endswith(f":{port}") and bits[3] == "LISTENING" and bits[4] != "0":
                subprocess.run(["taskkill", "/PID", bits[4], "/F"], capture_output=True)
    else:
        proc.terminate()
    for _ in range(50):
        if not up(port):
            return
        time.sleep(0.2)


def run(script, engine, devices, port):
    env = dict(os.environ, ENGINE=engine, DEVICES=devices, E2E_PORT=str(port), PYTHONIOENCODING="utf-8")
    proc = None
    if script not in OWN_SERVER:
        data = os.path.join(HERE, ".tmp", f"data-{port}")
        copy_data(data)
        senv = dict(os.environ, DND_TRACKER_DATA=data, **SERVER_ENV.get(script, {}))
        log = open(os.path.join(HERE, ".tmp", f"server-{port}.log"), "w")
        proc = subprocess.Popen([APP_PY, "run.py", "--port", str(port), "--no-browser", "--lan"], cwd=APP_DIR, env=senv, stdout=log, stderr=subprocess.STDOUT)
        for _ in range(150):
            if up(port):
                break
            time.sleep(0.2)
        else:
            stop(proc, port)
            return f"{script} [{engine}/{devices}]: the test server didn't start"
        subprocess.run([sys.executable, os.path.join(HERE, "prep.py")], env=dict(env, PORT=str(port)), capture_output=True)
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, script)], cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
    finally:
        if proc:
            stop(proc, port)
    keep = [l.strip() for l in out.splitlines() if l.strip().startswith(("FAIL", "PROBLEMS: [", "Traceback")) or " passed, " in l or l.startswith("ERRORS")]
    keep = [k for k in keep if k != "PROBLEMS: []"]
    if os.environ.get("E2E_VERBOSE"):
        print(out)
    return f"{script} [{engine}/{devices}]: " + (" | ".join(dict.fromkeys(keep)) or out.strip().splitlines()[-1:][0] if out.strip() else "no output")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scripts", nargs="*", help="e2e_*.py files in tests/e2e (default with --all: every one)")
    ap.add_argument("--all", action="store_true", help="run every e2e_*.py")
    ap.add_argument("--engine", default="chromium", help="chromium, firefox, webkit, or all")
    ap.add_argument("--devices", default="mixed", help="phones, laptops, tablets or mixed (for the scripts that use it)")
    ap.add_argument("--port", type=int, default=5077)
    a = ap.parse_args()
    scripts = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "e2e_*.py"))) if a.all or not a.scripts else a.scripts
    engines = ["chromium", "firefox", "webkit"] if a.engine == "all" else [a.engine]
    bad = 0
    for e in engines:
        for s in scripts:
            line = run(s, e, a.devices, a.port)
            bad += ("FAIL" in line or "Traceback" in line or "didn't start" in line)
            print(line, flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
