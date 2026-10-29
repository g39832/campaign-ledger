"""The Players page notices a dead online link by itself: a fake tunnel reports an address that no
longer exists; within two checks the page shows 'stopped working' and Get a new link."""
import json, threading, time
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.sync_api import sync_playwright

DM = DM_URL
SHOTS = SHOTS_DIR
results = []


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


class Fake(BaseHTTPRequestHandler):  # what cloudflared's metrics would say for a dropped tunnel
    def do_GET(self):
        body = json.dumps({"hostname": "long-gone-dropped-link-zz9.trycloudflare.com"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 20249), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1300, "height": 900})
    pg.goto(DM + "/table"); pg.wait_for_timeout(2000)
    first = pg.locator("#online-body").inner_text()
    check("long-gone-dropped-link" in first and "stopped working" not in first, "at first the page shows the link (not checked yet)")
    t0 = time.time()
    while time.time() - t0 < 150 and not pg.locator("#new-link").count():
        pg.wait_for_timeout(5000)
    took = round(time.time() - t0)
    check(pg.locator("#new-link").count() == 1, f"by itself, within {took} s, the page says the link stopped working, with Get a new link")
    check("stopped working" in pg.locator("#online-body").inner_text(), "with the explanation")
    pg.locator("#online-body").screenshot(path=SHOTS + r"\online_dead.png")
    b.close()
srv.shutdown()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
