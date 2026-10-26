"""Routes and presets the other test files don't reach: every map and encounter
preset, portraits, campaign switching, set-turn and sort, journal links,
database download and snapshots, stopping the online link, players leaving."""
import io
import os
import sqlite3

import pytest
from PIL import Image

from tests.test_dice_map_players import remote


def test_every_map_preset_builds(api):
    camp = api.campaign()
    presets = api.get("/api/map-presets")["presets"]
    assert len(presets) >= 8
    for p in presets:
        m = api.post(f"/api/campaigns/{camp['id']}/maps", {"preset": p["key"]}, 201)["map"]
        assert m["cols"] > 0 and m["rows"] > 0 and m["terrain"], p["key"]
        assert api.get(f"/api/maps/{m['id']}")["map"]["name"]


def test_every_encounter_preset_builds_a_ready_fight(api):
    camp = api.campaign()
    api.character(camp["id"], name="Aria", max_hp=20)
    presets = api.get("/api/encounter-presets")["presets"]
    assert len(presets) >= 10
    for p in presets:
        r = api.post(f"/api/campaigns/{camp['id']}/encounter-presets/{p['key']}", {}, 201)
        enc = api.get(f"/api/encounters/{r['encounter_id']}")
        enemies = [c for c in enc["combatants"] if c["kind"] == "enemy"]
        assert enemies and any(c["name"] == "Aria" for c in enc["combatants"]), p["key"]
        for e in enemies:
            assert e["max_hp"] > 0 and e["statblock"].get("attacks"), (p["key"], e["name"])
        st = api.get(f"/api/maps/{r['map_id']}")
        assert len(st["tokens"]) == len(enc["combatants"]), p["key"]


def test_monster_book_monsters_all_have_attacks():
    from app.monster_book import MONSTERS
    assert len(MONSTERS) >= 33
    for m in MONSTERS:
        assert m["attacks"].strip() and m["max_hp"] > 0 and m["ac"] > 0, m["name"]


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_portrait_upload_and_remove(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Aria")
    r = api.c.post(f"/api/characters/{ch['id']}/portrait", data={"file": (png_bytes(), "me.png", "image/png")},
                   content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    name = r.get_json()["character"]["portrait"]
    assert name and api.c.get(f"/api/uploads/{name}").status_code == 200
    bad = api.c.post(f"/api/characters/{ch['id']}/portrait", data={"file": (io.BytesIO(b"nope"), "x.txt", "text/plain")},
                     content_type="multipart/form-data")
    assert bad.status_code == 400
    assert api.delete(f"/api/characters/{ch['id']}/portrait")["character"]["portrait"] is None


def test_switching_campaigns(api):
    a, b = api.campaign("A"), api.campaign("B")
    api.post(f"/api/campaigns/{a['id']}/activate")
    assert api.get("/api/campaigns")["active_id"] == a["id"]
    api.post(f"/api/campaigns/{b['id']}/activate")
    assert api.get("/api/campaigns")["active_id"] == b["id"]


def test_set_turn_and_sort(api):
    camp = api.campaign()
    eid = api.encounter(camp["id"])["encounter"]["id"]
    st = api.post(f"/api/encounters/{eid}/combatants", {"quick": {"name": "Orc", "max_hp": 15, "count": 3}})
    ids = [c["id"] for c in st["combatants"]]
    api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": ids[0]}, 400)  # not started yet
    for i, cid in enumerate(ids):
        api.patch(f"/api/combatants/{cid}", {"changes": {"init_roll": {"from": None, "to": 5 + i * 5}}})
    st = api.post(f"/api/encounters/{eid}/sort")
    assert [c["id"] for c in st["combatants"]] == ids[::-1], "highest initiative first"
    api.post(f"/api/encounters/{eid}/start")
    st = api.post(f"/api/encounters/{eid}/set-turn", {"combatant_id": ids[1]})
    assert st["encounter"]["current_id"] == ids[1]
    assert any("DM set the turn to" in e["message"] for e in st["log"])


def test_journal_links_both_ways(api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Aria")
    e = api.post(f"/api/campaigns/{camp['id']}/journal", {"title": "Met Aria", "kind": "session", "body": "hi"}, 201)["entry"]
    r = api.c.put(f"/api/journal/{e['id']}/links", json={"links": [{"type": "character", "id": ch["id"]}]})
    assert r.status_code == 200, r.get_data(as_text=True)
    back = api.get(f"/api/links/character/{ch['id']}")
    assert any(x["id"] == e["id"] for x in back["entries"])


def test_database_download_and_snapshot_list(api, app):
    api.campaign("Keep me")
    r = api.c.get("/api/backup/database")
    assert r.status_code == 200 and r.data[:16] == b"SQLite format 3\x00"
    snaps = api.get("/api/backup/snapshots")["snapshots"]
    assert snaps and all(s["name"].endswith(".sqlite3") for s in snaps)
    path = os.path.join(app.config["BACKUP_DIR"], snaps[0]["name"])
    names = [n for (n,) in sqlite3.connect(path).execute("SELECT name FROM campaigns")]
    assert "Keep me" in names, "the download is a real copy of the data"


def test_online_stop_is_safe_when_not_running(app, api):
    s = api.post("/api/online/stop", {})
    assert s["running"] is False and s["url"] is None
    r = app.test_client().post("/api/online/stop", json={}, headers={"CF-Connecting-IP": "203.0.113.5"})
    assert r.status_code in (401, 403), "only the DM can stop it"


def test_player_leave_frees_the_character(app, api):
    camp = api.campaign()
    ch = api.character(camp["id"], name="Aria")
    code = api.post(f"/api/campaigns/{camp['id']}/join-code", {"action": "new"})["join_code"]
    p = remote(app, "192.168.1.61")
    p.post("/api/join", {"code": code, "name": "Sam", "character_id": ch["id"]})
    assert p.get("/api/play/state")["character"]["name"] == "Aria"
    p.post("/api/play/leave", {})
    assert p.c.get("/api/play/state").status_code == 401
    q = remote(app, "192.168.1.62")
    q.post("/api/join", {"code": code, "name": "Jo", "character_id": ch["id"]})  # Aria is free again
