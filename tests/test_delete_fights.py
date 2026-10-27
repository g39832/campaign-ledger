"""Finished fights can be deleted from the combat history (one, or all of them). Their map
stays, without that fight's tokens; running fights have to be ended first."""
from tests.test_dice_map_players import battlemap, joined, tok  # noqa: F401  (fixtures)


def test_delete_a_finished_fight_keeps_its_map(api, battlemap):
    eid, mid, camp = battlemap["eid"], battlemap["mid"], battlemap["camp"]
    api.post(f"/api/encounters/{eid}/start")
    api.post("/api/rolls", {"expression": "1d20", "campaign_id": camp["id"], "encounter_id": eid}, 201)
    api.delete(f"/api/encounters/{eid}", expect=400)
    api.post(f"/api/encounters/{eid}/end")
    api.delete(f"/api/encounters/{eid}")
    api.get(f"/api/encounters/{eid}", expect=404)
    m = api.get(f"/api/maps/{mid}")
    assert m["map"]["encounter_id"] is None and not any(t["display"].startswith("Bandit") for t in m["tokens"])
    assert [t["display"] for t in m["tokens"] if t["character_id"]] == ["Aria"], "the hero stays on the map"
    assert api.get(f"/api/rolls?campaign_id={camp['id']}")["rolls"], "dice rolls stay"
    assert api.get(f"/api/characters/{battlemap['a']['id']}")["character"]["name"] == "Aria", "heroes are untouched"


def test_delete_all_finished(api, joined):
    camp = joined["camp"]
    ids = []
    for n in ("One", "Two", "Three"):
        eid = api.encounter(camp["id"], n)["encounter"]["id"]
        api.post(f"/api/encounters/{eid}/combatants", {"quick": {"name": "Rat", "max_hp": 2}})
        api.post(f"/api/encounters/{eid}/start")
        ids.append(eid)
    for eid in ids[:2]:
        api.post(f"/api/encounters/{eid}/end")
    r = api.delete(f"/api/campaigns/{camp['id']}/encounters/finished")
    assert sorted(r["deleted"]) == sorted(ids[:2])
    left = [e["id"] for e in api.get(f"/api/campaigns/{camp['id']}/encounters")["encounters"]]
    assert left == [ids[2]], "the running one stays"
