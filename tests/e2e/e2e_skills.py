"""E2E: type a skill by hand on a sheet, it sticks and rolls with it; clear it, it's worked out again."""
import json, urllib.request, uuid
from common import APP_DIR, DM_URL, LAN_IP, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402,F401  (paths and addresses for this computer)
from playwright.sync_api import sync_playwright
import engine

DM = DM_URL
SHOTS = SHOTS_DIR
results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


YAM = 3
before = call("GET", f"/api/characters/{YAM}")["character"]["derived"]["skills"]["athletics"]
with sync_playwright() as p:
    b = engine.launch(p)
    pg = b.new_page(viewport={"width": 1300, "height": 1000})
    pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    pg.goto(f"{DM}/characters/{YAM}"); pg.wait_for_timeout(800)
    if pg.locator("#skills").is_hidden():
        pg.locator("[data-fold='skills']").click(); pg.wait_for_timeout(300)
    box = pg.locator("[data-skillset='athletics']")
    check(box.get_attribute("placeholder") == (f"+{before}" if before >= 0 else str(before)), f"the box shows the worked-out {before} as a hint")
    box.fill("8"); pg.wait_for_timeout(2500)
    check(pg.locator("#skill-athletics").inner_text() == "+8", "Athletics now shows +8 on the sheet")
    check(call("GET", f"/api/characters/{YAM}")["character"]["derived"]["skills"]["athletics"] == 8, "and it's saved")
    pg.screenshot(path=SHOTS + "/skills_set.png", full_page=False)
    pg.reload(); pg.wait_for_timeout(1000)
    if pg.locator("#skills").is_hidden():
        pg.locator("[data-fold='skills']").click(); pg.wait_for_timeout(300)
    check(pg.locator("[data-skillset='athletics']").input_value() == "8" and pg.locator("#skill-athletics").inner_text() == "+8", "still +8 after a reload")
    pg.locator("#skill-athletics").click(); pg.wait_for_timeout(2500)
    roll = call("GET", "/api/rolls?campaign_id=1")["rolls"][0]
    check("Athletics" in roll["label"] and "+8" in roll["expression"].replace(" ", ""), f"rolling Athletics uses +8 ({roll['expression']})")
    pg.locator("[data-skillset='athletics']").fill(""); pg.wait_for_timeout(2500)
    check(call("GET", f"/api/characters/{YAM}")["character"]["derived"]["skills"]["athletics"] == before, "cleared: worked out again")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
