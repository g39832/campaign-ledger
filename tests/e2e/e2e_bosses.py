"""The creature library's Bosses section, clicked: tick Boss, it moves to the Bosses section at the top
with a crown; Bosses only filters; untick puts it back; other creatures and the editor are unchanged."""
import json, re, urllib.request, uuid
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


for c in call("GET", "/api/creatures")["creatures"]:  # in this copy, start with no bosses
    if c["boss"]:
        call("PATCH", f"/api/creatures/{c['id']}", {"changes": {"boss": {"from": True, "to": False}}})
lib = call("GET", "/api/creatures")["creatures"]
check(all(c["boss"] is False for c in lib), f"starting with no bosses ({len(lib)} creatures)")
with sync_playwright() as p:
    b = engine.launch(p)
    for vw, vh in ((1400, 950), (390, 844)):
        pg = b.new_page(viewport={"width": vw, "height": vh}); pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
        pg.goto(DM + "/creatures"); pg.wait_for_timeout(1500)
        items = lambda: [x.strip() for x in pg.locator("#list li").all_inner_texts()]
        check(pg.locator("#list .lib-head").count() == 0, f"[{vw}px] no Bosses section while there are no bosses")
        btn = lambda name: pg.locator("#list li button").filter(has=pg.locator(".t", has_text=re.compile(r"^" + re.escape(name) + r"$")))
        btn("Mimic Boss").first.click(); pg.wait_for_timeout(600)
        box = pg.locator("#editor .sb-boss input")
        check(box.count() == 1 and not box.is_checked(), "the stat block has a Boss box, unticked")
        box.check(); pg.wait_for_timeout(2200)
        check(next(c for c in call("GET", "/api/creatures")["creatures"] if c["name"] == "Mimic Boss")["boss"] is True, "ticking it saves")
        heads = [x.strip() for x in pg.locator("#list .lib-head").all_inner_texts()]
        first = pg.locator("#list li").nth(1).inner_text()
        check(heads and heads[0].lower().startswith("bosses") and "Mimic Boss" in first, f"Mimic Boss is at the top under Bosses ({heads}; {first.splitlines()[0]!r})")
        check(pg.locator("#list li button.is-boss .ico").count() == 1, "with a crown")
        btn("Dreadnought").first.click(); pg.wait_for_timeout(500); pg.locator("#editor .sb-boss input").check(); pg.wait_for_timeout(2200)
        check([x.strip() for x in pg.locator("#list .lib-head").all_inner_texts()][0].lower().startswith("bosses") and pg.locator("#list li button.is-boss").count() == 2, "two bosses")
        pg.locator("#boss-only").check(); pg.wait_for_timeout(300)
        names = [x.split("\n")[0].strip() for x in pg.locator("#list li button .t").all_inner_texts()]
        check(sorted(names) == ["Dreadnought", "Mimic Boss"], f"Bosses only shows just the bosses ({names})")
        pg.fill("#q", "dread"); pg.wait_for_timeout(300)
        check([x.split("\n")[0].strip() for x in pg.locator("#list li button .t").all_inner_texts()] == ["Dreadnought"], "and search still works with it")
        pg.fill("#q", ""); pg.screenshot(path=SHOTS + rf"\bosses_{vw}_{engine.NAME}.png", full_page=False)
        pg.locator("#boss-only").uncheck(); pg.wait_for_timeout(300)
        check(len(pg.locator("#list li button").all()) == len(lib), "everything's listed again")
        # the editor still works (the attacks form) and it still goes into fights
        check(pg.locator("#editor .mrows").count() == 2, "the stat block's attacks form is still there")
        # untick both
        for n in ("Mimic Boss", "Dreadnought"):
            btn(n).first.click(); pg.wait_for_timeout(400); pg.locator("#editor .sb-boss input").uncheck(); pg.wait_for_timeout(2000)
        check(pg.locator("#list .lib-head").count() == 0 and all(not c["boss"] for c in call("GET", "/api/creatures")["creatures"]), "unticking puts them back with the rest")
        # the Monster Book still opens
        pg.locator("#book-toggle").click(); pg.wait_for_timeout(800)
        check(pg.locator("#book-list li").count() > 10, "the Monster Book still opens")
        pg.close()
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
