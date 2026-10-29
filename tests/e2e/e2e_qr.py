"""The Players page's join QR code: it shows (the Wi-Fi link with the code when there's no online
link), points at /join?code=..., and 'Show it big' fills the screen; on a phone-sized screen too."""
import json, re, urllib.parse, urllib.request, uuid
from playwright.sync_api import sync_playwright
from common import DM_URL, LAN_IP, SHOTS_DIR  # noqa: E402
import engine

results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM_URL + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


code = call("GET", "/api/campaigns/1/players")["join_code"] or call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
online = call("GET", "/api/online")
with sync_playwright() as p:
    b = engine.launch(p)
    for vw, vh in ((1300, 900), (390, 844)):
        pg = b.new_page(viewport={"width": vw, "height": vh}); pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
        pg.goto(DM_URL + "/table"); pg.wait_for_selector("#qr-box:not([hidden]) img", timeout=15000); pg.wait_for_timeout(500)
        src = pg.locator("#qr-box img").get_attribute("src")
        target = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)["url"][0]
        want = (online["url"] if online.get("running") and online.get("url") and not online.get("broken") else f"http://{LAN_IP}:")
        check(target.endswith("/join?code=" + code) and target.startswith(want), f"[{vw}px] the QR code is the join link with the code ({target})")
        ok = pg.evaluate("(s) => new Promise((r) => { const i = new Image(); i.onload = () => r(i.naturalWidth > 100); i.onerror = () => r(false); i.src = s; })", src)
        check(ok, "its picture loads")
        pg.locator("#qr-box").scroll_into_view_if_needed(); pg.locator("#qr-box").screenshot(path=SHOTS_DIR + rf"\qr_box_{vw}_{engine.NAME}.png")
        pg.locator("#qr-big").click(); pg.wait_for_timeout(500)
        big = pg.locator(".qr-big img")
        box = big.bounding_box()
        check(big.count() == 1 and box["width"] > min(vw, vh) * 0.5, f"Show it big fills the screen ({box['width']:.0f}px wide)")
        check(code in pg.locator(".qr-big").inner_text(), "with the join code written under it")
        pg.screenshot(path=SHOTS_DIR + rf"\qr_big_{vw}_{engine.NAME}.png")
        pg.locator(".qr-big").click(); pg.wait_for_timeout(300)
        check(pg.locator(".qr-big").count() == 0, "tapping closes it")
        # the link really opens the join page with the code filled in
        jp = b.new_page(viewport={"width": 390, "height": 844})
        jp.goto(target.replace(f"http://{LAN_IP}:", "http://127.0.0.1:") if target.startswith("http://") else DM_URL + "/join?code=" + code)
        check(jp.locator("input[name=code]").input_value() == code, "opening it fills in the join code")
        jp.close(); pg.close()
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
