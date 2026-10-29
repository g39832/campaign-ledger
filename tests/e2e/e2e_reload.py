"""After an update (the server restarts), open pages reload themselves: a player's /play and the
DM's map. It waits while someone is typing."""
import json, os, re, subprocess, time, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright

APP = APP_DIR; SP = TMP_DIR
DATA = SP + r"\e2e-data3"; PORT = 5079; B = f"http://127.0.0.1:{PORT}"
results = []


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def kill(p):
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    for line in subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout.splitlines():
        bits = line.split()
        if len(bits) >= 5 and bits[1].endswith(f":{PORT}") and bits[3] == "LISTENING":
            subprocess.run(["taskkill", "/PID", bits[4], "/F"], capture_output=True)
    for _ in range(50):
        try:
            urllib.request.urlopen(B + "/api/join/build", timeout=0.5); time.sleep(0.2)
        except Exception:
            return


def start():
    env = dict(os.environ, DND_TRACKER_DATA=DATA)
    p = subprocess.Popen([APP + r"\.venv\Scripts\python.exe", "run.py", "--port", str(PORT), "--no-browser", "--lan"], cwd=APP, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(B + "/api/join/build"); return p
        except Exception:
            time.sleep(0.3)
    raise SystemExit("server didn't start")


import shutil, sqlite3
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
src = sqlite3.connect(f"file:{APP}\\data\\dnd_tracker.sqlite3?mode=ro", uri=True); dst = sqlite3.connect(DATA + r"\dnd_tracker.sqlite3"); src.backup(dst); dst.close()
srv = start()
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    dm = b.new_page(); dm.goto(B + "/"); dm.wait_for_timeout(1500)
    dm.evaluate("window.__old = true")
    code = json.load(urllib.request.urlopen(urllib.request.Request(B + "/api/campaigns/1/join-code", data=b'{"action":"new"}', method="POST", headers={"Content-Type": "application/json"})))["join_code"]
    for pl in json.load(urllib.request.urlopen(B + "/api/campaigns/1/players"))["players"]:
        urllib.request.urlopen(urllib.request.Request(B + f"/api/players/{pl['id']}", method="DELETE"))
    lan = f"http://{LAN_IP}:{PORT}"
    pp = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    pp.goto(lan + "/join"); pp.fill("input[name=code]", code); pp.fill("input[name=name]", "reload test")
    pp.wait_for_selector("#char-field:not([hidden])"); pp.select_option("select[name=character_id]", index=1)
    pp.click("button[type=submit]"); pp.wait_for_url(re.compile("/play")); pp.wait_for_timeout(1500); pp.evaluate("window.__old = true")
    sheet = b.new_page(); sheet.goto(B + "/characters/1"); sheet.wait_for_timeout(1500)
    sheet.evaluate("window.__old = true")
    sheet.evaluate("document.querySelector('input[type=text], input:not([type]), textarea').focus()")  # someone is typing
    kill(srv); srv = start()                      # the update
    dm.wait_for_timeout(14000)
    check(dm.evaluate("!window.__old"), "the DM's page reloaded itself onto the update")
    check(pp.evaluate("!window.__old") and "/play" in pp.url, "a player's screen reloaded itself too (still in the game)")
    check(sheet.evaluate("!!window.__old"), "the sheet waits while someone is typing in it")
    sheet.evaluate("document.activeElement && document.activeElement.blur()")
    sheet.wait_for_timeout(11000)
    check(sheet.evaluate("!window.__old"), "...and reloads once they've stopped")
    b.close()
kill(srv)
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
