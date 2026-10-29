"""Handouts, clicked: the DM sends a picture + note to everyone from the Players page; it pops up on
Lux's phone within a second or two; a second one only to Moni pops up on hers, not on Lux's; both
stay in the Handouts list and reopen; the DM deletes one and it's gone."""
import json, re, struct, time, urllib.request, uuid, zlib, os
from playwright.sync_api import sync_playwright
from common import DM_URL, LAN_URL, SHOTS_DIR, TMP_DIR  # noqa: E402
import engine

results, problems = [], []


def call(m, path, body=None):
    data = json.dumps(dict(body or {}, op_id=uuid.uuid4().hex)).encode() if m != "GET" else None
    return json.load(urllib.request.urlopen(urllib.request.Request(DM_URL + path, data=data, method=m, headers={"Content-Type": "application/json"})))


def check(c, msg):
    results.append((bool(c), msg)); print(("  PASS " if c else "  FAIL ") + msg, flush=True)


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PIC = os.path.join(TMP_DIR, "letter.png")
open(PIC, "wb").write(png(120, 80, (200, 160, 60)))
for pl in call("GET", "/api/campaigns/1/players")["players"]:
    call("DELETE", f"/api/players/{pl['id']}")
chars = {c["name"]: c for c in call("GET", "/api/campaigns/1/characters")["characters"]}
code = call("POST", "/api/campaigns/1/join-code", {"action": "new"})["join_code"]
with sync_playwright() as p:
    b = engine.launch(p)

    def join(name, who):
        pg = b.new_context(viewport={"width": 390, "height": 844}, **engine.mobile(), has_touch=True).new_page()
        pg.on("pageerror", lambda e: problems.append(f"{who} JS error: {e}"))
        pg.goto(LAN_URL + "/join"); pg.fill("input[name=code]", code); pg.fill("input[name=name]", who)
        pg.wait_for_selector("#char-field:not([hidden])"); pg.select_option("select[name=character_id]", value=str(chars[name]["id"]))
        pg.click("button[type=submit]"); pg.wait_for_url(re.compile("/play")); pg.wait_for_timeout(2500)
        return pg
    lux, moni = join("Lux Fedelis", "Lux plays"), join("Moni Easter", "Moni plays")
    dm = b.new_page(viewport={"width": 1300, "height": 950}); dm.on("pageerror", lambda e: problems.append(f"DM JS error: {e}"))
    dm.goto(DM_URL + "/table"); dm.wait_for_timeout(1500)
    f = dm.locator("#handout-form")
    check(f.count() == 1, "the Players page has a Handouts section")
    f.locator("[name=title]").fill("A letter sealed with black wax"); f.locator("[name=body]").fill("Meet us at the old mill.\nCome alone.")
    f.locator("[name=file]").set_input_files(PIC)
    t0 = time.time()
    f.locator("button[type=submit]").click()
    lux.wait_for_selector(".handout-pop", timeout=10000)
    took = time.time() - t0
    card = lux.locator(".handout-card")
    check("A letter sealed with black wax" in card.inner_text() and "Come alone." in card.inner_text() and card.locator("img").count() == 1,
          f"it pops up on Lux's phone with the picture and the note ({took:.1f} s)")
    check(lux.evaluate("(() => { const i = document.querySelector('.handout-card img'); return i && i.complete && i.naturalWidth > 0; })()") or lux.wait_for_timeout(800) or
          lux.evaluate("(() => { const i = document.querySelector('.handout-card img'); return i && i.naturalWidth > 0; })()"), "the picture loads on the phone")
    lux.screenshot(path=SHOTS_DIR + rf"\handout_phone_{engine.NAME}.png")
    moni.wait_for_selector(".handout-pop", timeout=10000)
    check("black wax" in moni.locator(".handout-card").inner_text(), "and on Moni's (it's for everyone)")
    lux.locator(".handout-card").get_by_role("button", name="Close").click(); moni.locator(".handout-card").get_by_role("button", name="Close").click()
    lux.wait_for_timeout(500)
    check(lux.locator(".handout-pop").count() == 0, "Close puts it away")
    # one only for Moni
    f.locator("[name=everyone]").uncheck()
    f.locator("label.handout-char", has_text="Moni Easter").locator("input").check()
    f.locator("[name=title]").fill("A whisper only you hear"); f.locator("[name=body]").fill("The druid knows.")
    f.locator("button[type=submit]").click()
    moni.wait_for_selector(".handout-pop", timeout=10000)
    check("whisper only you hear" in moni.locator(".handout-card").inner_text(), "the private one pops up on Moni's phone")
    lux.wait_for_timeout(2500)
    check(lux.locator(".handout-pop").count() == 0 and "whisper" not in lux.locator("body").inner_text(), "and never on Lux's")
    moni.locator(".handout-card").get_by_role("button", name="Close").click(); moni.wait_for_timeout(300)
    # the list: reopen
    items = moni.locator(".handout-list li")
    check(items.count() == 2, f"Moni's Handouts list has both ({items.count()})")
    items.filter(has_text="black wax").locator("button").click(); moni.wait_for_timeout(400)
    check("Come alone." in moni.locator(".handout-card").inner_text(), "tapping one in the list opens it again")
    moni.locator(".handout-card").get_by_role("button", name="Close").click()
    check(lux.locator(".handout-list li").count() == 1, "Lux's list has only the one for everyone")
    # it doesn't pop up again after a reload (it's been seen)
    lux.reload(); lux.wait_for_timeout(3000)
    check(lux.locator(".handout-pop").count() == 0, "after a reload it doesn't pop up again")
    check(moni.locator("#me .handout-list li").count() == 2 and lux.locator("#me .handout-list li").count() == 1, "on the phones the list is in the character box")
    # the character sheets
    sh = b.new_page(viewport={"width": 1300, "height": 950}); sh.on("pageerror", lambda e: problems.append(f"sheet JS error: {e}"))
    sh.goto(DM_URL + f"/characters/{chars['Moni Easter']['id']}"); sh.wait_for_timeout(1500)
    if sh.locator("[data-fold-body=handouts]").first.is_hidden():
        sh.locator("[data-fold=handouts]").click(); sh.wait_for_timeout(300)
    items = sh.locator("#sheet-handouts .sheet-handout")
    check(items.count() == 2 and "Sent to Moni Easter" in items.first.inner_text() and "Sent to everyone" in items.nth(1).inner_text(),
          f"Moni's sheet lists both her handouts ({[x.replace(chr(10), ' ') for x in items.all_inner_texts()]})")
    items.nth(1).click(); sh.wait_for_timeout(400)
    check("Come alone." in sh.locator(".handout-card").inner_text() and sh.locator(".handout-card img").count() == 1, "clicking one on the sheet opens it big")
    sh.locator("#sheet-handouts").scroll_into_view_if_needed(); sh.screenshot(path=SHOTS_DIR + rf"\handout_sheet_{engine.NAME}.png")
    sh.locator(".handout-card").get_by_role("button", name="Close").click()
    sh.goto(DM_URL + f"/characters/{chars['Lux Fedelis']['id']}"); sh.wait_for_timeout(1500)
    if sh.locator("[data-fold-body=handouts]").first.is_hidden():
        sh.locator("[data-fold=handouts]").click(); sh.wait_for_timeout(300)
    check(sh.locator("#sheet-handouts .sheet-handout").count() == 1, "Lux's sheet lists only the one for everyone")
    sh.close()
    # the DM's list, delete
    sent = dm.locator("#handout-sent li.handout-item")
    check(sent.count() == 2 and "To Moni Easter" in sent.first.inner_text(), "the DM sees what was sent and to whom")
    dm.screenshot(path=SHOTS_DIR + rf"\handout_dm_{engine.NAME}.png", full_page=True)
    sent.first.get_by_role("button", name=re.compile("Delete")).click(); dm.wait_for_timeout(250)
    sent.first.get_by_role("button", name=re.compile("Delete|again|sure", re.I)).click(); dm.wait_for_timeout(2500)
    check(dm.locator("#handout-sent li.handout-item").count() == 1 and moni.locator(".handout-list li").count() == 1, "Delete takes it off the DM's list and Moni's screen")
    b.close()
fails = [m for ok, m in results if not ok]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed"); [print("FAILED:", f) for f in fails]
print("PROBLEMS:", problems)
