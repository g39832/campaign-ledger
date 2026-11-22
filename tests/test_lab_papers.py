"""Loose papers in the laboratory (app/lab_papers.py): every floor has its clues, a hero next to one
reads it and gets it as a handout (only them), the top floor's printout carries the station
coordinates chip, and the papers never change the floor's enemies or lockers."""
from app import lab_papers as P
from app.dungeon import LAB_FLOORS
from app.maps import BLOCKING
from tests.test_dice_map_players import joined  # noqa: F401  (fixture)


def _floors(api, camp):
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "lab"}, 201)
    floors = [st]
    for _ in range(LAB_FLOORS - 1):
        nxt = api.post(f"/api/maps/{floors[-1]['map']['id']}/next-level", {})["next_level"]
        floors.append(api.get(f"/api/maps/{nxt['map_id']}"))
    return floors


def test_every_floor_has_its_papers_and_the_top_has_the_coordinates(api, joined):
    floors = _floors(api, joined["camp"])
    for level, f in enumerate(floors, 1):
        papers = [c for c in f["map"]["chests"] if c["kind"] == "papers"]
        assert sorted(c["name"] for c in papers) == sorted(t for t, _ in P.PAPERS[level]), level
        assert all(not c["hidden"] and c["loot"][0]["type"] == "note" and c["loot"][0]["desc"] for c in papers)
        squares = [(c["x"], c["y"]) for c in f["map"]["chests"]]
        assert len(squares) == len(set(squares)), "one thing per square"
        taken = {(int(t["x"]), int(t["y"])) for t in f["tokens"]}
        assert not taken & {(c["x"], c["y"]) for c in papers}, "never under a token"
        assert [c["kind"] for c in f["map"]["chests"]].count("lab") == 3  # the lockers are all still there
    top = next(c for c in floors[-1]["map"]["chests"] if c["name"] == "Station coordinates printout")
    assert any(i["name"] == "Station coordinates chip" for i in top["loot"])
    boss = next(r for r in floors[-1]["map"]["dungeon"]["rooms"] if r["kind"] == "boss")
    x0, y0, x1, y1 = boss["box"]
    assert x0 <= top["x"] <= x1 and y0 <= top["y"] <= y1, "the coordinates are behind the Director"


def test_the_clues_never_name_moni():
    text = " ".join(t + " " + b for floor in P.PAPERS.values() for t, b in floor).lower()
    assert "moni" not in text and "easter" not in text
    assert "voss" in text and "ironclad" in text and "chimera" in text and "e-5" in text


def test_reading_a_paper_gives_the_reader_a_handout_and_the_chip_can_be_taken(api, joined):
    camp, a, b, pa, pb = joined["camp"], joined["a"], joined["b"], joined["pa"], joined["pb"]
    floors = _floors(api, camp)
    top = floors[-1]["map"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": top["id"]})
    paper = next(c for c in top["chests"] if c["name"] == "Station coordinates printout")
    s = api.post(f"/api/maps/{top['id']}/tokens", {"character_id": a["id"], "x": 0, "y": 0}, 201)
    tok = next(t for t in s["tokens"] if t["character_id"] == a["id"])
    # stand right next to it (any open neighbouring square)
    terrain = top["terrain"]
    near = next((paper["x"] + dx, paper["y"] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and terrain.get(f"{paper['x'] + dx},{paper['y'] + dy}") not in BLOCKING
                and not any((c["x"], c["y"]) == (paper["x"] + dx, paper["y"] + dy) for c in top["chests"])
                and not any((int(t["x"]), int(t["y"])) == (paper["x"] + dx, paper["y"] + dy) for t in s["tokens"]))
    api.post(f"/api/tokens/{tok['id']}/move", {"x": near[0], "y": near[1], "free": True})
    # the room may still be in fog for the player: the DM shows the whole floor for this test
    st = api.get(f"/api/maps/{top['id']}")
    if st["map"]["fog_enabled"]:
        api.patch(f"/api/maps/{top['id']}", {"changes": {"fog_enabled": {"from": True, "to": False}}})
    pa.post(f"/api/play/chests/{paper['id']}/open", {})
    got = pa.get("/api/play/state")["handouts"]
    mine = [h for h in got if h["title"] == "Station coordinates printout"]
    assert len(mine) == 1 and "ORBIT-7" in mine[0]["body"] and mine[0]["just_you"] and "Found:" in mine[0]["body"]
    assert not any(h["title"] == "Station coordinates printout" for h in pb.get("/api/play/state")["handouts"]), "only the reader"
    pa.post(f"/api/play/chests/{paper['id']}/open", {})  # reading it again: no second copy
    assert len([h for h in pa.get("/api/play/state")["handouts"] if h["title"] == "Station coordinates printout"]) == 1
    chip = next(i for i in pa.post(f"/api/play/chests/{paper['id']}/open", {})["chest"]["loot"] if i["name"] == "Station coordinates chip")
    pa.post(f"/api/play/chests/{paper['id']}/take", {"item": chip["id"]})
    sheet = api.get(f"/api/characters/{a['id']}")["character"]
    assert any(r["name"] == "Station coordinates chip" for r in sheet["equipment"])


def test_papers_dont_change_the_floors_enemies_or_lockers():
    import random
    from app.lab import FLOORS  # noqa: F401  the rolls for enemies/lockers use their own Random; papers use another
    r1, r2 = random.Random(5), random.Random(5)
    assert [t for t, _ in P.papers_for(3, r1)] == [t for t, _ in P.papers_for(3, r2)]


def test_the_dm_cant_add_empty_papers_from_the_chest_list(api):
    kinds = [k["key"] for k in api.get("/api/chest-kinds")["kinds"]]
    assert "papers" not in kinds and "drop" not in kinds
