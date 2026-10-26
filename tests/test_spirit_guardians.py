"""Lux's homebrew Spirit Guardians: a 15 ft square around her; each foe makes a Wisdom
save against her (a real save, even with the roll-to-hit house rule on) or takes 3d8,
nothing on a success; and again at the start of each of its turns while it lasts."""
from tests.test_spells import Loaded, cast, table, loaded, who, eff  # noqa: F401  (fixtures)

SG = {"name": "Spirit Guardians", "effect": "damage", "level": 3, "dice": "3d8", "damage_type": "radiant", "hit": "wis",
      "save_half": False, "force_save": True, "area": "15 ft square", "concentration": True, "condition": "Spirit guardians",
      "ongoing": "3d8", "ongoing_type": "radiant", "ongoing_save": True, "rounds": 100,
      "notes": "Small angelic spirits surround me in a 15 by 15 cube"}


def test_wisdom_save_or_3d8_even_with_the_house_rule(table, loaded):
    t = table
    api = t["api"]
    ch = api.get(f"/api/characters/{t['cleric']['id']}")["character"]
    api.set_char(ch, spells=ch["spells"] + [SG])
    idx = len(ch["spells"])
    loaded.next(4, 4, 4, 2, 20)  # 3d8 = 12; Goblin 1 rolls 2 (fails DC 14), Goblin 2 rolls 20 (saves)
    st = cast(t, "Bram", idx, ["Goblin 1", "Goblin 2"])
    assert st["cast"]["lands"] == "save", "a real Wisdom save, not the roll-to-hit rule"
    res = {r["name"]: r for r in st["cast"]["targets"]}
    assert res["Goblin 1"]["how"] == "failed" and res["Goblin 1"]["amount"] == 12 and who(st, "Goblin 1")["hp"] == 28
    assert res["Goblin 2"]["how"] == "saved" and res["Goblin 2"]["amount"] is None and who(st, "Goblin 2")["hp"] == 40
    assert eff(who(st, "Bram"), "Concentrating")["spell"] == "Spirit Guardians"
    on = eff(who(st, "Goblin 1"), "Spirit guardians")["ongoing"]
    assert on == {"dice": "3d8", "kind": "damage", "type": "radiant", "save": "wis", "dc": 14, "half": False}
    # its turn: saves this time -> no damage
    api.post(f"/api/encounters/{t['eid']}/start")
    api.post(f"/api/encounters/{t['eid']}/set-turn", {"combatant_id": t["by"]["Ilse"]["id"]})
    loaded.next(5, 5, 5, 19)
    st = api.post(f"/api/encounters/{t['eid']}/next")
    while st["encounter"]["current_id"] != t["by"]["Goblin 1"]["id"]:
        st = api.post(f"/api/encounters/{t['eid']}/next")
    assert who(st, "Goblin 1")["hp"] == 28
    msg = [e["message"] for e in st["log"] if e["message"].startswith("Spirit Guardians: Goblin 1")]
    assert msg == ["Spirit Guardians: Goblin 1 saves at the start of their turn (19 vs DC 14) — no damage"], msg
    # next time it fails: 3d8
    loaded.next(3, 3, 3, 1)
    for _ in range(len(st["combatants"])):
        st = api.post(f"/api/encounters/{t['eid']}/next")
        if st["encounter"]["current_id"] == t["by"]["Goblin 1"]["id"]:
            break
    assert who(st, "Goblin 1")["hp"] == 19
