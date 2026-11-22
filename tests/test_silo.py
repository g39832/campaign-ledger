"""The missile silo (app/silo_layout.py, app/silo.py): four levels down round the launch shaft, all
new kinds of block, Steven's machines on every level, and the launch bay's ending: turn all three
abort keys (missiles down, Steven escapes), reach Steven's lift (Steven caught, missiles launch), or
let the countdown run out (both bad)."""
import re
from pathlib import Path

import pytest

from app import silo as SILO
from app.dungeon import SOLID, generate, path_len
from app.maps import BLOCKING, TERRAIN
from app.silo_layout import ESCAPE_AT, SILO_LEVELS, STEVEN_AT, abort_spots
from tests.test_dice_map_players import joined  # noqa: F401  (fixture)

NEW_BLOCKS = {"concrete", "hazard", "catwalk", "cable", "coolant", "silodoor", "lift", "pad", "escape", "concretewall",
              "beacon", "shaft", "missile", "fueltank", "pipes", "reactor", "console", "bunk", "rack", "crate"}


@pytest.mark.parametrize("seed", [1, 7, 42, 999, 123456])
def test_every_level_joins_up_and_uses_the_silo_blocks(seed):
    for level in range(1, SILO_LEVELS + 1):
        g = generate("silo", seed, level)
        kinds = set(g["terrain"].values())
        assert kinds <= set(TERRAIN), kinds - set(TERRAIN)
        assert "missile" in kinds and "shaft" in kinds and "concrete" in kinds
        assert len(kinds & NEW_BLOCKS) >= 10, "lots of different blocks, not one look"
        assert g["terrain"][f"{g['start'][0]},{g['start'][1]}"] not in SOLID
        if level < SILO_LEVELS:
            assert g["terrain"][f"{g['exit'][0]},{g['exit'][1]}"] == "lift"
            assert path_len(g["terrain"], g["start"], g["exit"], g["cols"], g["rows"]) is not None
        else:
            assert g["exit"] is None and g["terrain"][f"{ESCAPE_AT[0]},{ESCAPE_AT[1]}"] == "escape"
            for x, y in abort_spots():
                assert path_len(g["terrain"], g["start"], (x, y + 1), g["cols"], g["rows"]) is not None


def test_every_new_block_is_drawn_and_named_in_the_map_view():
    js = (Path(__file__).resolve().parents[1] / "app/static/js/mapview.js").read_text(encoding="utf-8")
    for k in NEW_BLOCKS:
        assert re.search(r"\b" + k + r": \{ fill: \"#[0-9a-f]{6}\", label: \"[^\"]+\", silo: true", js), k


def _levels(api, camp):
    st = api.post(f"/api/campaigns/{camp['id']}/dungeons", {"theme": "silo"}, 201)
    out = [st]
    for _ in range(SILO_LEVELS - 1):
        nxt = api.post(f"/api/maps/{out[-1]['map']['id']}/next-level", {})["next_level"]
        out.append(api.get(f"/api/maps/{nxt['map_id']}"))
    return out


def test_each_level_is_stocked_and_the_bottom_is_the_launch_bay(api, joined):
    levels = _levels(api, joined["camp"])
    for n, st in enumerate(levels, 1):
        enemies = [t for t in st["tokens"] if t["kind"] == "enemy"]
        assert enemies, n
        squares = [(c["x"], c["y"]) for c in st["map"]["chests"]]
        assert len(squares) == len(set(squares))
        for c in st["map"]["chests"]:
            assert st["map"]["terrain"][f"{c['x']},{c['y']}"] not in BLOCKING
        assert any(c["kind"] == "papers" for c in st["map"]["chests"])
    bay = levels[-1]
    names = [t["display"] for t in bay["tokens"]]
    robot = next(t for t in bay["tokens"] if t["display"].startswith("Ironclad Harlan"))
    assert robot["size"] == 3 and robot["kind"] == "enemy"
    steven = next(t for t in bay["tokens"] if t["display"] == "Steven Voss")
    assert steven["kind"] == "npc" and not steven["combatant_id"], "Steven doesn't fight"
    assert (int(steven["x"]), int(steven["y"])) == STEVEN_AT
    kinds = [c["kind"] for c in bay["map"]["chests"]]
    assert kinds.count("abort") == 3 and kinds.count("escape") == 1
    assert bay["map"]["silo"]["outcome"] is None and bay["map"]["silo"]["keys_total"] == 3
    assert "Steven Voss" in names


def _bay_live(api, joined):
    camp, a = joined["camp"], joined["a"]
    bay = _levels(api, camp)[-1]["map"]
    mid = bay["id"]
    api.post(f"/api/campaigns/{camp['id']}/live-map", {"map_id": mid})
    api.patch(f"/api/maps/{mid}", {"changes": {"fog_enabled": {"from": True, "to": False}}})
    s = api.get(f"/api/maps/{mid}")
    tok = next((t for t in s["tokens"] if t.get("character_id") == a["id"]), None)
    if tok is None:
        s = api.post(f"/api/maps/{mid}/tokens", {"character_id": a["id"], "x": 3, "y": 12}, 201)
        tok = next(t for t in s["tokens"] if t.get("character_id") == a["id"])
    return mid, s, tok


def _stand(api, tok, x, y):
    api.post(f"/api/tokens/{tok['id']}/move", {"x": x, "y": y, "free": True})


def test_turning_all_three_keys_stops_the_launch_and_steven_escapes(api, joined):
    pa, pb = joined["pa"], joined["pb"]
    mid, s, tok = _bay_live(api, joined)
    keys = sorted((c for c in s["map"]["chests"] if c["kind"] == "abort"), key=lambda c: c["x"])
    for i, k in enumerate(keys):
        _stand(api, tok, k["x"], k["y"] + 1)
        pa.post(f"/api/play/chests/{k['id']}/open", {})
        silo = api.get(f"/api/maps/{mid}")["map"]["silo"]
        if i < 2:
            assert silo["outcome"] is None and silo["keys"] == i + 1
    st = api.get(f"/api/maps/{mid}")
    assert st["map"]["silo"]["outcome"] == "aborted"
    assert not any(t["display"] == "Steven Voss" for t in st["tokens"]), "he went up his lift"
    assert "missile" in st["map"]["terrain"].values(), "the missiles stay in their tubes"
    for p in (pa, pb):  # everyone gets the handout
        assert any(h["title"] == "The missiles are down" for h in p.get("/api/play/state")["handouts"])
    esc = next(c for c in st["map"]["chests"] if c["kind"] == "escape")
    _stand(api, tok, ESCAPE_AT[0] - 1, ESCAPE_AT[1] - 1)
    assert "over" in pa.post(f"/api/play/chests/{esc['id']}/open", {}, 409)["error"]


def test_going_after_steven_catches_him_and_the_missiles_launch(api, joined):
    pa = joined["pa"]
    mid, s, tok = _bay_live(api, joined)
    esc = next(c for c in s["map"]["chests"] if c["kind"] == "escape")
    _stand(api, tok, ESCAPE_AT[0] - 1, ESCAPE_AT[1] - 1)
    pa.post(f"/api/play/chests/{esc['id']}/open", {})
    st = api.get(f"/api/maps/{mid}")
    assert st["map"]["silo"]["outcome"] == "caught"
    assert "missile" not in st["map"]["terrain"].values(), "the tubes are empty"
    assert any(t["display"] == "Steven Voss" for t in st["tokens"]), "they have him"
    assert any(h["title"] == "The missiles launch" for h in pa.get("/api/play/state")["handouts"])
    key = next(c for c in st["map"]["chests"] if c["kind"] == "abort")
    _stand(api, tok, key["x"], key["y"] + 1)
    pa.post(f"/api/play/chests/{key['id']}/open", {}, 409)
    # the DM can put it all back
    st = api.post(f"/api/maps/{mid}/silo", {"action": "reset"})
    assert st["map"]["silo"]["outcome"] is None and "missile" in st["map"]["terrain"].values()
    assert any(t["display"] == "Steven Voss" for t in st["tokens"])
    assert all(not c["opened"] for c in st["map"]["chests"] if c["kind"] in ("abort", "escape"))


def test_you_must_stand_next_to_a_key(api, joined):
    pa = joined["pa"]
    mid, s, tok = _bay_live(api, joined)
    key = next(c for c in s["map"]["chests"] if c["kind"] == "abort")
    _stand(api, tok, 3, 12)
    pa.post(f"/api/play/chests/{key['id']}/open", {}, 403)
    assert api.get(f"/api/maps/{mid}")["map"]["silo"]["keys"] == 0


def test_the_countdown_runs_with_the_robot_fight_and_launches_when_it_runs_out(api, joined):
    mid, s, tok = _bay_live(api, joined)
    eid = s["map"]["encounter_id"]
    assert s["map"]["silo"]["rounds_left"] is None, "no countdown before the robot's fight"
    for _ in range(3):
        api.post(f"/api/maps/{mid}/silo", {"action": "less"})  # 8 -> 2
    api.post(f"/api/encounters/{eid}/start", {})
    st = api.get(f"/api/maps/{mid}")
    assert st["map"]["silo"]["rounds_left"] == 2
    seen_round = 1
    for _ in range(200):
        enc = api.post(f"/api/encounters/{eid}/next", {})
        r = (enc.get("encounter") or enc)["round"]
        if r != seen_round:
            seen_round = r
            silo = api.get(f"/api/maps/{mid}")["map"]["silo"]
            if silo["outcome"]:
                break
            assert silo["rounds_left"] == 2 - (r - 1)
    silo = api.get(f"/api/maps/{mid}")["map"]["silo"]
    assert silo["outcome"] == "timeout" and seen_round == 3
    st = api.get(f"/api/maps/{mid}")
    assert "missile" not in st["map"]["terrain"].values()
    assert not any(t["display"] == "Steven Voss" for t in st["tokens"])


def test_the_robot_is_built_from_harlans_moves():
    from app.monster_book import BY_NAME
    from app.prison_monsters import SILO_NAMES, TACTICS
    r = BY_NAME[SILO.ROBOT]
    assert r["boss"] and r["has_phase2"] and r["legendary_resistance"] == 2 and r["creature_type"].startswith("Huge")
    for move in ("Smash", "Stunning Smash", "Earth Shattter", "Shield Bash", "Rally"):
        assert move in r["attacks"] + r["spells"] + r["legendary"], move
    assert all(n in TACTICS for n in SILO_NAMES)


def test_the_dm_cant_add_silo_controls_from_the_chest_list(api):
    kinds = [k["key"] for k in api.get("/api/chest-kinds")["kinds"]]
    assert "abort" not in kinds and "escape" not in kinds
