"""A picture for a creature (its icon): uploaded on its stat block; shown in the library, for its
enemies in a fight (already there too) and on their map tokens, for players as well; kept in backups."""
import base64
import io

from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def upload(api, cid, data=PNG, kind="image/png"):
    return api.c.post(f"/api/creatures/{cid}/portrait", data={"file": (io.BytesIO(data), "pic.png", kind)}, content_type="multipart/form-data")


def test_a_creature_gets_a_picture(api):
    c = api.post("/api/creatures", {"name": "Owlbear", "max_hp": 59, "ac": 13, "attacks": "Claw +7 to hit 2d8+5"}, 201)["creature"]
    assert c["portrait"] is None
    r = upload(api, c["id"])
    assert r.status_code == 200, r.get_data(as_text=True)
    pic = r.get_json()["creature"]["portrait"]
    assert pic and pic.endswith(".png")
    assert next(x for x in api.get("/api/creatures")["creatures"] if x["id"] == c["id"])["portrait"] == pic
    assert api.c.get(f"/api/uploads/{pic}").status_code == 200
    bad = upload(api, c["id"], b"not an image", "text/plain")
    assert bad.status_code == 400 and "PNG" in bad.get_json()["error"]
    gone = api.delete(f"/api/creatures/{c['id']}/portrait")
    assert gone["creature"]["portrait"] is None


def test_enemies_and_their_tokens_show_it(api, battlemap):
    camp, eid, mid = battlemap["camp"], battlemap["eid"], battlemap["mid"]
    c = api.post("/api/creatures", {"name": "Wolf", "max_hp": 11, "ac": 13, "attacks": "Bite +4 to hit 2d4+2", "campaign_id": camp["id"]}, 201)["creature"]
    api.post(f"/api/encounters/{eid}/combatants", {"creature_id": c["id"], "count": 1})
    api.post(f"/api/maps/{mid}/tokens/from-encounter")
    pic = upload(api, c["id"]).get_json()["creature"]["portrait"]       # added after the wolf joined the fight
    wolf = next(x for x in api.get(f"/api/encounters/{eid}")["combatants"] if x["name"] == "Wolf")
    assert wolf["portrait"] == pic
    assert tok(api.get(f"/api/maps/{mid}"), "Wolf")["portrait"] == pic
    bandit = next(x for x in api.get(f"/api/encounters/{eid}")["combatants"] if x["name"] == "Bandit 1")
    assert bandit["portrait"] is None                                     # quick-added enemies: no picture
    # the players see it on their map, and may load the file
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    pa = battlemap["pa"]
    assert tok(pa.get("/api/play/state")["map"], "Wolf")["portrait"] == pic
    assert pa.c.get(f"/api/uploads/{pic}").status_code == 200


def test_backups_keep_the_picture(api, battlemap):
    c = api.post("/api/creatures", {"name": "Imp", "max_hp": 10, "ac": 13}, 201)["creature"]   # library (no campaign)
    pic = upload(api, c["id"]).get_json()["creature"]["portrait"]
    exp = api.c.get("/api/backup/export").get_json()
    assert pic in exp["data"]["files"]
    assert any(x.get("portrait") == pic for x in exp["data"]["library"])
