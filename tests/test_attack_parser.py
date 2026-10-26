"""The browser's stat-block parser (L.attackLines in core.js), run in Node when it's
installed. It turns lines like "Bite 1d4" into the attack buttons on the map and
the combat screen, so a regression here hides every monster's attacks."""
import json
import os
import shutil
import subprocess

import pytest

from app.monster_book import MONSTERS

CORE = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "core.js")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js isn't installed")

RUNNER = r"""
const src = require("fs").readFileSync(process.argv[1], "utf8");
eval(src.match(/const CONDITION_WORDS[\s\S]*?const attackNotes[^\n]*\n/)[0] + "global.T = { attackLines, attackNotes };");
const lines = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(lines.map((t) => ({ acts: T.attackLines(t), notes: T.attackNotes(t) }))));
"""


def parse(texts):
    out = subprocess.run([NODE, "-e", RUNNER, CORE], input=json.dumps(texts), capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_shorthand_and_book_style():
    got = parse(["Bite 1d4\nSpread 1d20 must beat a 5", "Snipe shot - 1d20 damage",
                 "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) slashing damage.",
                 "Fire bolt +5 2d10", "Healing word heal 1d4+2", "Web: Restrained 10 rounds",
                 "Poison breath DC 13 1d20", "can summon a mad mushroom"])
    bite, spread = got[0]["acts"]
    assert (bite["name"], bite["dmg"], bite["hit"]) == ("Bite", "1d4", None)
    assert (spread["name"], spread["check"], spread["beat"]) == ("Spread", "1d20", 5)
    assert got[1]["acts"][0] | {} == got[1]["acts"][0] and got[1]["acts"][0]["dmg"] == "1d20", "said damage, so it's damage"
    sc = got[2]["acts"][0]
    assert (sc["name"], sc["hit"], sc["dmg"]) == ("Scimitar", "+4", "1d6+2")
    fb = got[3]["acts"][0]
    assert (fb["name"], fb["hit"], fb["dmg"]) == ("Fire bolt", "+5", "2d10")
    hw = got[4]["acts"][0]
    assert (hw["name"], hw["heal"], hw["dmg"]) == ("Healing word", True, "1d4+2")
    web = got[5]["acts"][0]
    assert (web["name"], web["condition"], web["rounds"], web["dmg"]) == ("Web", "Restrained", 10, None)
    pb = got[6]["acts"][0]
    assert (pb["name"], pb["dc"]) == ("Poison breath", 13)
    assert got[7] == {"acts": [], "notes": ["can summon a mad mushroom"]}
    area = parse(["Cold Breath (Recharge 5–6). Exhales an icy blast in a 15-foot cone. 5d8 cold damage", "Fireball 8d6 range 150 20 ft radius", "Bite 1d4"])
    assert area[0]["acts"][0]["aimArea"] == {"kind": "cone", "size": 15, "range": 0}
    assert area[1]["acts"][0]["aimArea"] == {"kind": "circle", "size": 20, "range": 150}
    assert area[2]["acts"][0]["aimArea"] is None


def test_every_monster_book_monster_gets_buttons():
    got = parse([m["attacks"] for m in MONSTERS])
    for m, g in zip(MONSTERS, got):
        acts = g["acts"]
        assert acts, f"{m['name']} would show no attack buttons"
        for a in acts:
            assert a.get("dmg") or a.get("check") or a.get("condition"), (m["name"], a)
    breath = {m["name"]: g for m, g in zip(MONSTERS, got)}["Young Red Dragon"]["acts"]
    assert next(a for a in breath if a["name"].startswith("Fire Breath"))["area"], "breath weapons hit everyone in the area"
