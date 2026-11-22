"""Steven Voss — Harlan Voss's father, a level 18 artificer boss — and his relay drones.

add_to_library() puts both in the creature library (or updates them, keeping their ids) with
pictures drawn here with Pillow: Steven's is a pair of worker goggles, the drone's a small rotor
drone with the same goggle lens. The drone tricks themselves are in app/relay.py.
"""
import json
import os
import uuid

from . import fields as F
from .db import now_iso

STEVEN = {
    "name": "Steven Voss",
    "creature_type": "Medium humanoid (human), Level 18 Artificer",
    "cr": "14",
    "max_hp": 350,
    "ac": 19,
    "initiative_mod": 2,
    "speed": "30 ft. (fly 90 ft. in phase 2)",
    "abilities": {"str": 14, "dex": 14, "con": 16, "int": 20, "wis": 14, "cha": 12},
    "attacks": "\n".join([
        # up front
        "Thunder Gauntlet: +3 to hit, 2d8+5 thunder damage, look punch",
        "Arc Wrench: +3 to hit, 1d10+5 lightning damage, look sparks",
        # giant metal arms built out of whatever is around him
        "Titan Arm: +3 to hit, 4d10 bludgeoning damage, Prone 1 rounds, 20 ft square, range 60, 2 turn cooldown, look punch",
        "Iron Grip: +3 to hit, 2d10 bludgeoning damage, Restrained 2 rounds, ranged, 3 turn cooldown, look punch",
    ]),
    "spells": "\n".join([
        "Deploy Drones: summon 2 Voss Drone, relay, 4 at once, 2 turn cooldown",
        # metal bending: a straight steel wall anywhere within 60 ft; a third wall folds the oldest back down (how he moves them)
        "Metal Bend: steel wall, 30 ft line, range 60, 1 turn cooldown, look rock",
        "Fire Bolt 4d10, look flames",
        "Shocking Grasp 4d8, look sparks",
        "Thunderwave 2d8, look arcane",
        "Shatter: 3d8 thunder damage, 2 turn cooldown, look arcane",
        "Fireball: 8d6 fire damage, 3 turn cooldown, look flames",
        "Cone of Cold: 8d8 cold damage, 4 turn cooldown, look frost",
        "Cure Wounds heal 4d8+5, 2 turn cooldown, look holy",
    ]),
    "traits": "\n".join([
        "Spellcasting. Level 18 artificer (Intelligence): spell save DC 19, +3 to hit with spell attacks.",
        "Metal Bend. He bends the metal around him into straight steel walls (30 ft long, anywhere within 60 ft). "
        "Two stand at once; bending a third folds the oldest back into the floor, so he moves his walls around the fight.",
        "Relay Drones. His Voss Drones cast his spells again on anyone the spell hits within 30 ft of a drone. "
        "When someone else casts a spell within 30 ft of a drone, Steven records it and can cast it back once (up to 3 kept).",
        "Titan Arms. Giant metal arms tear up out of the floor, walls and scrap around him to slam or grab foes up to 60 ft away.",
        "Worker Goggles. He sees through his drones' eyes.",
        "Overdrive (phase 2). Below half HP his arms throw, drag and shock: every phase 2 move Shocks (lose one action next turn) and shoves or pulls.",
        "Hollow Star Heart (phase 2). At half HP he drives his shard of the Hollow Star into his chest. Scrap metal forms out of "
        "nothing and folds into a pair of steel wings around him: he flies (90 ft of movement) and gains the wing and star moves.",
        "Soul of Artifice. Steeped in his own inventions: +6 to all saving throws.",
        "Stolen Spells. He can cast a spell his drones copied on his turn, or as one of his legendary actions.",
        "Father of Harlan Voss.",
    ]),
    "resistances": "lightning, thunder",
    "senses": "darkvision 60 ft. (goggles), passive Perception 18",
    "languages": "Common, Dwarvish, Gnomish",
    "notes": "Fights from the middle: drones out first, spells on clumps of heroes, Titan Arm on anyone who closes in, gauntlet when cornered.",
    "boss": True,
    "legendary": "Drone Zap: +3 to hit, 2d6 lightning damage, ranged, look sparks",
    "legendary_per_round": 2,
    "has_phase2": True,
    "phase2": "\n".join([
        "Colossus Arms: +3 to hit, 6d10 bludgeoning damage, Shocked 1 rounds, push 20 ft, 30 ft square, range 60, 3 turn cooldown, look quake",
        "Tesla Lash: +3 to hit, 4d8 lightning damage, Shocked 1 rounds, push 15 ft, 15 ft cone, range 0, look sparks",
        "Magnet Pull: +3 to hit, 2d8 lightning damage, Shocked 1 rounds, pull all the way, ranged, look sparks",
        "Piston Slam: +3 to hit, 3d10+5 bludgeoning damage, Shocked 1 rounds, push 25 ft, reach 10 ft, look punch",
        "Overload: +3 to hit, 5d8 lightning damage, Shocked 1 rounds, push 10 ft, 20 ft radius, range 0, 2 turn cooldown, look sparks",
        # the Hollow Star Heart: steel wings and the star shard in his chest
        "Wing Scythe: +3 to hit, 4d10+5 slashing damage, Shocked 1 rounds, push 15 ft, 15 ft cone, range 0, 1 turn cooldown, look slash",
        "Feather Storm: +3 to hit, 4d10 piercing damage, Shocked 1 rounds, push 10 ft, 20 ft radius, range 60, 3 turn cooldown, look arrow",
        "Star Core Beam: +3 to hit, 6d10 radiant damage, Shocked 1 rounds, push 30 ft, 60 ft line, range 0, 4 turn cooldown, look laser",
        "Wing Guard Slam: +3 to hit, 3d8+5 bludgeoning damage, Shocked 1 rounds, pull 10 ft, reach 10 ft, 2 turn cooldown, look punch",
    ]),
    "legendary_resistance": 2,
    "tagline": "Harlan's father. Every machine in the room answers to him.",
}

DRONE = {
    "name": "Voss Drone",
    "creature_type": "Tiny construct",
    "cr": "1/2",
    "max_hp": 12,
    "ac": 15,
    "initiative_mod": 3,
    "speed": "0 ft., fly 40 ft. (hover)",
    "abilities": {"str": 4, "dex": 16, "con": 12, "int": 14, "wis": 12, "cha": 4},
    "attacks": "Zap: +3 to hit, 1d6 lightning damage, ranged, look sparks",
    "traits": "\n".join([
        "Spell Relay. When Steven Voss casts a spell, this drone casts it again on anyone the spell hits within 30 ft of it (his DC and to hit).",
        "Spell Recorder. When anyone else casts a spell within 30 ft of it, Steven can cast that spell back once.",
    ]),
    "immunities": "poison, psychic",
    "condition_immunities": "Poisoned, Charmed, Frightened",
    "senses": "darkvision 60 ft., passive Perception 11",
    "boss": False,
}

PICS = {"Steven Voss": "voss-steven-voss.png", "Voss Drone": "voss-drone.png"}


def _goggles(d, S, cx, cy, scale, strap=True):
    """A pair of brass worker goggles centred on (cx, cy) (in 0-100 units)."""
    def E(x, y, r, fill, outline=None, w=2.0):
        d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill, outline=outline, width=max(1, int(S * w)))
    brass, dark_brass, leather = (214, 160, 70, 255), (120, 82, 30, 255), (92, 58, 34, 255)
    k = scale
    if strap:
        d.rounded_rectangle([(cx - 46 * k) * S, (cy - 6 * k) * S, (cx + 46 * k) * S, (cy + 6 * k) * S], radius=5 * k * S, fill=leather,
                            outline=(60, 36, 20, 255), width=max(1, int(S)))
        for x in (-40, 40):  # rivets on the strap
            E(cx + x * k, cy, 1.8 * k, (230, 200, 140, 255))
    d.rounded_rectangle([(cx - 6 * k) * S, (cy - 4 * k) * S, (cx + 6 * k) * S, (cy + 4 * k) * S], radius=2 * k * S, fill=dark_brass)  # bridge
    for side in (-1, 1):
        x = cx + side * 20 * k
        E(x, cy, 17 * k, brass, dark_brass, 2.5)                       # brass rim
        E(x, cy, 13 * k, (40, 46, 52, 255), (90, 64, 26, 255), 1.5)   # inner ring
        E(x, cy, 11 * k, (70, 200, 230, 255))                          # lens
        E(x - 4 * k, cy - 4 * k, 3.5 * k, (220, 250, 255, 230))       # glint
        for a in range(6):                                             # rim bolts
            import math
            t = a * math.pi / 3 + 0.3
            E(x + math.cos(t) * 15 * k, cy + math.sin(t) * 15 * k, 1.3 * k, (250, 220, 150, 255))


def draw(name, size=256):
    from PIL import Image, ImageDraw
    S = size / 100.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def circ(cx, cy, r, fill, outline=None, w=1.5):
        d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill, outline=outline, width=max(1, int(S * w)))

    # workshop disc with a hazard-orange rim
    circ(50, 50, 48, (34, 30, 28, 255), (240, 140, 30, 255), 3)
    if name == "Voss Drone":
        steel = (150, 160, 172, 255)
        d.line([(20 * S, 30 * S), (80 * S, 30 * S)], fill=steel, width=int(3 * S))   # rotors
        for x in (24, 76):
            d.line([(x * S, 30 * S), (x * S, 42 * S)], fill=steel, width=int(3 * S))
        d.rounded_rectangle([28 * S, 38 * S, 72 * S, 66 * S], radius=10 * S, fill=(96, 90, 82, 255), outline=(214, 160, 70, 255), width=int(2 * S))
        _goggles(d, S, 50, 52, 0.42, strap=False)
        d.line([(40 * S, 66 * S), (34 * S, 78 * S)], fill=steel, width=int(2 * S))
        d.line([(60 * S, 66 * S), (66 * S, 78 * S)], fill=steel, width=int(2 * S))
        circ(66, 79, 2.5, (120, 220, 255, 255))  # relay spark
    else:
        # hazard stripes behind the goggles, then the goggles big in the middle
        for i in range(-3, 4):
            x = 50 + i * 16
            d.polygon([((x - 4) * S, 82 * S), ((x + 4) * S, 82 * S), ((x + 12) * S, 70 * S), ((x + 4) * S, 70 * S)], fill=(240, 180, 30, 90))
        _goggles(d, S, 50, 46, 1.0)
        # a gear tooth ring at the bottom: engineer
        import math
        for a in range(10):
            t = a * math.pi / 5
            circ(50 + math.cos(t) * 9, 80 + math.sin(t) * 9, 2.6, (150, 160, 172, 255))
        circ(50, 80, 8, (150, 160, 172, 255))
        circ(50, 80, 3.5, (34, 30, 28, 255))
    # keep it round (tokens are discs)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def add_to_library(conn, upload_dir):
    """Add (or refresh) Steven Voss and the Voss Drone in the creature library. Returns {name: id}."""
    ids = {}
    for block in (STEVEN, DRONE):
        fn = PICS[block["name"]]
        draw(block["name"]).save(os.path.join(upload_dir, fn), "PNG", optimize=True)
        vals = {k: block[k] for k in F.CREATURE if k in block}
        row = conn.execute("SELECT id FROM creatures WHERE lower(name) = lower(?) AND campaign_id IS NULL", (block["name"],)).fetchone()
        sets = {**{k: (json.dumps(v) if isinstance(v, dict) else int(v) if isinstance(v, bool) else v) for k, v in vals.items()},
                "portrait": fn, "updated_at": now_iso()}
        if row:
            conn.execute(f"UPDATE creatures SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), row["id"]))
            ids[block["name"]] = row["id"]
        else:
            sets.update(uid=uuid.uuid4().hex, campaign_id=None, created_at=now_iso())
            cur = conn.execute(f"INSERT INTO creatures ({', '.join(sets)}) VALUES ({', '.join('?' * len(sets))})", tuple(sets.values()))
            ids[block["name"]] = cur.lastrowid
    return ids
