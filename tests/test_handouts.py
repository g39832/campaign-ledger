"""Player handouts: the DM sends a note and/or picture to everyone or to chosen characters; each
player sees only the ones meant for them (and may load only those pictures); backups keep them."""
import base64
import io

from tests.test_dice_map_players import joined  # noqa: F401  (fixture)

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def send(api, cid, **form):
    data = {k: v for k, v in form.items() if k != "png"}
    if form.get("png"):
        data["file"] = (io.BytesIO(PNG), "letter.png", "image/png")
    return api.c.post(f"/api/campaigns/{cid}/handouts", data=data, content_type="multipart/form-data")


def test_everyone_and_just_one(api, joined):
    cid, a, b = joined["camp"]["id"], joined["a"], joined["b"]
    r = send(api, cid, title="The king is dead", body="Long live the queen.")
    assert r.status_code == 201, r.get_data(as_text=True)
    r = send(api, cid, title="For Aria only", body="Meet me at midnight.", to=str(a["id"]), png=True)
    assert r.status_code == 201
    secret = r.get_json()["handout"]
    sa = joined["pa"].get("/api/play/state")["handouts"]
    sb = joined["pb"].get("/api/play/state")["handouts"]
    assert [x["title"] for x in sa] == ["For Aria only", "The king is dead"]
    assert [x["title"] for x in sb] == ["The king is dead"]
    assert "to" not in sa[0]                                         # players aren't told who else got it
    # the picture: Aria may load it, Bram may not
    assert joined["pa"].c.get(f"/api/uploads/{secret['image']}").status_code == 200
    assert joined["pb"].c.get(f"/api/uploads/{secret['image']}").status_code == 404
    # the DM's list, and delete
    assert len(api.get(f"/api/campaigns/{cid}/handouts")["handouts"]) == 2
    api.delete(f"/api/handouts/{secret['id']}")
    assert [x["title"] for x in joined["pa"].get("/api/play/state")["handouts"]] == ["The king is dead"]


def test_only_the_dm_sends_and_nonsense_is_refused(api, joined):
    cid = joined["camp"]["id"]
    assert send(api, cid).status_code == 400                         # nothing to send
    assert send(api, cid, title="x", to="999999").status_code == 400  # not a character here
    r = send(api, cid, title="x", png=False)
    assert r.status_code == 201
    assert joined["pa"].c.post(f"/api/campaigns/{cid}/handouts", data={"title": "hi"}, content_type="multipart/form-data").status_code == 403
    assert joined["pa"].c.get(f"/api/campaigns/{cid}/handouts").status_code == 403
    assert joined["pa"].c.delete(f"/api/handouts/{r.get_json()['handout']['id']}").status_code == 403


def test_backups_keep_handouts(api, joined):
    cid, a = joined["camp"]["id"], joined["a"]
    send(api, cid, title="Map scrap", body="X marks the spot", to=str(a["id"]), png=True)
    exp = api.c.get("/api/backup/export").get_json()
    camp = next(c for c in exp["data"]["campaigns"] if c["id"] == cid)
    hd = camp["handouts"][0]
    assert hd["title"] == "Map scrap" and hd["image"] in exp["data"]["files"]
    # import it as a copy: the handout comes with it, still for (the copy of) Aria
    import json as _json
    r = api.c.post("/api/backup/inspect", data={"file": (io.BytesIO(_json.dumps(exp).encode()), "b.json", "application/json")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()["token"]
    r = api.post("/api/backup/import", {"token": token, "decisions": {camp["uid"]: "copy"}})
    newc = next(c for c in api.get("/api/campaigns")["campaigns"] if c["name"].endswith("(imported copy)"))
    hs = api.get(f"/api/campaigns/{newc['id']}/handouts")["handouts"]
    assert [h["title"] for h in hs] == ["Map scrap"]
    copied_aria = next(ch for ch in api.get(f"/api/campaigns/{newc['id']}/characters")["characters"] if ch["name"] == "Aria")
    assert hs[0]["to"] == [copied_aria["id"]]


def test_the_sheet_lists_a_characters_handouts(api, joined):
    cid, a, b = joined["camp"]["id"], joined["a"], joined["b"]
    send(api, cid, title="To all", body="Hello everyone")
    send(api, cid, title="Just Aria", body="Psst", to=str(a["id"]))
    ha = api.get(f"/api/characters/{a['id']}/handouts")["handouts"]
    hb = api.get(f"/api/characters/{b['id']}/handouts")["handouts"]
    assert [(x["title"], x["just_you"]) for x in ha] == [("Just Aria", True), ("To all", False)]
    assert [x["title"] for x in hb] == ["To all"]
    assert joined["pa"].c.get(f"/api/characters/{a['id']}/handouts").status_code == 403   # the DM's sheet only


def test_read_state_is_kept_on_the_server_per_character(api, joined):
    """Opening a handout marks it read for that character on the server (so a new phone or a new
    address doesn't pop every old note up again); it's per character, and only for notes they can see."""
    cid, a, b = joined["camp"]["id"], joined["a"], joined["b"]
    everyone = send(api, cid, title="To all", body="Hello").get_json()["handout"]
    secret = send(api, cid, title="Just Bram", body="Psst", to=str(b["id"])).get_json()["handout"]
    sa = {x["title"]: x for x in joined["pa"].get("/api/play/state")["handouts"]}
    assert sa["To all"]["read"] is False
    joined["pa"].post(f"/api/play/handouts/{everyone['id']}/read", {"op_id": "r1"})
    joined["pa"].post(f"/api/play/handouts/{everyone['id']}/read", {"op_id": "r2"})   # twice is fine
    assert joined["pa"].get("/api/play/state")["handouts"][0]["read"] is True           # read for Aria...
    sb = {x["title"]: x for x in joined["pb"].get("/api/play/state")["handouts"]}
    assert sb["To all"]["read"] is False and sb["Just Bram"]["read"] is False           # ...not for Bram
    # Aria can't touch Bram's private note (or one that doesn't exist); the DM's own page isn't a player
    joined["pa"].post(f"/api/play/handouts/{secret['id']}/read", {"op_id": "r3"}, 404)
    joined["pa"].post("/api/play/handouts/999999/read", {"op_id": "r4"}, 404)
    assert api.c.post(f"/api/play/handouts/{everyone['id']}/read", json={}).status_code == 401
    sb = {x["title"]: x for x in joined["pb"].get("/api/play/state")["handouts"]}
    assert sb["Just Bram"]["read"] is False
    # deleting a handout takes its read marks with it
    api.delete(f"/api/handouts/{everyone['id']}")
    assert [x["title"] for x in joined["pa"].get("/api/play/state")["handouts"]] == []


def test_a_paper_found_on_the_map_starts_unread(app, api, joined):
    """Papers picked up on the map (lab clues) arrive unread for the reader only."""
    from app.db import get_db
    from app.lab_papers import give_handout
    cid, a = joined["camp"]["id"], joined["a"]
    with app.app_context():
        conn = get_db()
        assert give_handout(conn, cid, a["id"], "Incident report", "Voss pulls items back.", "Lab floor 2")
    x = joined["pa"].get("/api/play/state")["handouts"][0]
    assert x["title"] == "Incident report" and x["read"] is False and x["just_you"] is True
    assert joined["pb"].get("/api/play/state")["handouts"] == []


def test_upgrading_marks_every_existing_handout_read(data_dir):
    """v20: notes handed out before the server kept read marks count as read for everyone who
    got them, so nobody's screen fills with "New" (or pop-ups) after the update."""
    import os, sqlite3
    from app import create_app, db as appdb
    from tests.conftest import Api
    api = Api(create_app({"DATA_DIR": data_dir}).test_client())
    camp = api.campaign("Old")
    a = api.character(camp["id"], name="Aria", max_hp=20)
    b = api.character(camp["id"], name="Bram", max_hp=20)
    send(api, camp["id"], title="To all", body="x")
    send(api, camp["id"], title="Just Aria", body="y", to=str(a["id"]))
    path = os.path.join(data_dir, "dnd_tracker.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE handout_reads")
    conn.execute("PRAGMA user_version = 19")
    conn.commit(); conn.close()
    create_app({"DATA_DIR": data_dir})   # opening the app upgrades the database
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == appdb.SCHEMA_VERSION
    marks = sorted(conn.execute("SELECT h.title, c.name FROM handout_reads r JOIN handouts h ON h.id = r.handout_id "
                                "JOIN characters c ON c.id = r.character_id"))
    assert marks == [("Just Aria", "Aria"), ("To all", "Aria"), ("To all", "Bram")]
