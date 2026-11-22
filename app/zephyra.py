"""Zephyra Moonpetal: a level 15 Circle of the Moon druid NPC who fights beside the party (against
Steven Voss). Little pink alien antennas, big bug eyes. Her picture is just her initials (ZM) with the pink antennas.

Every attack and spell attack she has is +3 to hit (Grayson's rule); her spell attack is typed in on
the sheet (spell_attack_override), and every Wild Shape form's attacks are +3 too (app/wildshape.py).
Her save DC is the normal level 15 one (18). add() makes her, or refreshes her by name, keeping her id.
"""
import json
import uuid

from . import wildshape
from .db import now_iso

NAME = "Zephyra Moonpetal"

SPELLS = [
    {"name": "Produce Flame", "level": 0, "effect": "damage", "hit": "attack", "dice": "3d8", "damage_type": "fire",
     "notes": "A flame in her hand, thrown up to 30 ft"},
    {"name": "Thorn Whip", "level": 0, "effect": "damage", "hit": "attack", "dice": "3d6", "damage_type": "piercing",
     "notes": "A vine whip, melee spell attack, reach 30 ft"},
    {"name": "Cure Wounds", "level": 1, "effect": "heal", "dice": "2d8+mod", "cooldown": 1, "notes": "Touch"},
    {"name": "Entangle", "level": 1, "effect": "debuff", "hit": "str", "condition": "Restrained", "rounds": 10,
     "area": "20 ft square, range 90", "concentration": True, "repeat_save": True, "cooldown": 2,
     "notes": "Grasping weeds and vines"},
    {"name": "Moonbeam", "level": 2, "effect": "damage", "hit": "con", "dice": "2d10", "damage_type": "radiant",
     "area": "5 ft radius, range 120", "concentration": True, "save_half": True, "cooldown": 1,
     "notes": "A silver beam of moonlight"},
    {"name": "Call Lightning", "level": 3, "effect": "damage", "hit": "dex", "dice": "3d10", "damage_type": "lightning",
     "area": "5 ft radius, range 120", "concentration": True, "save_half": True, "cooldown": 2,
     "notes": "A storm cloud over the fight"},
    {"name": "Mass Cure Wounds", "level": 5, "effect": "heal", "dice": "3d8+mod", "targets": 6,
     "area": "30 ft radius, range 60", "cooldown": 3, "notes": "Up to six allies"},
    {"name": "Sunbeam", "level": 6, "effect": "damage", "hit": "con", "dice": "6d8", "damage_type": "radiant",
     "area": "60 ft line", "condition": "Blinded", "rounds": 1, "save_half": True, "cooldown": 3,
     "notes": "A beam of sunlight from her hand"},
]

CHARACTER = {
    "kind": "npc",
    "name": NAME,
    "race": "Starling (alien)",
    "class_name": "Druid",
    "subclass": "Circle of the Moon",
    "level": 15,
    "alignment": "Neutral good",
    "max_hp": 108, "current_hp": 108, "temp_hp": 0,
    "ac": 16,
    "speed": "30 ft.",
    "hit_dice": "15d8",
    "abilities": {"str": 10, "dex": 14, "con": 14, "int": 12, "wis": 20, "cha": 13},
    "save_profs": ["int", "wis"],
    "skill_profs": {"nature": 1, "animal_handling": 1, "perception": 1, "medicine": 1},
    "spellcasting_ability": "wis",
    "spell_attack_override": 3,
    "attacks": [{"name": "Moonwood Staff (Shillelagh)", "bonus": "+3", "damage": "1d8+5 bludgeoning", "notes": "Her glowing staff"}],
    "spells": SPELLS,
    "features": "\n".join([
        "Wild Shape (Circle of the Moon). A bonus action: she turns into a beast up to CR 5, or into an "
        "air, earth, fire or water elemental (two uses). Two uses, back after a rest. Her beast forms have "
        "their own HP; when a form drops to 0 she changes back and the leftover damage carries over.",
        "Trump card: Ancient Moon Behemoth. Once per long rest, on top of her two uses, she becomes a "
        "gargantuan moon beast (250 HP, AC 18, 3x3 squares): Crushing Jaws, Tail Sweep, Moonquake Stomp.",
        "No spells in beast form (druids can't until level 18).",
        "Every attack she makes, in any form, is +3 to hit.",
    ]),
    "appearance": "Small and quick, with two little pink alien antennas that bob when she talks and big shiny "
                  "bug eyes that reflect the light like a beetle's shell. The antennas stay on in every form "
                  "she takes.",
    "personality": "Curious, kind and a bit odd. Talks to plants and drones the same way.",
    "goals": "Stop Steven Voss before his machines tear up the wilds.",
    "notes": "Important NPC: fights beside the party against Steven Voss. All attacks +3 to hit. "
             "Spell save DC 18. Wild Shape is on the Combat page and the battle map.",
}


def add(conn, campaign_id):
    """Make Zephyra in this campaign (or refresh her), give her the Moon druid forms. Returns her id."""
    from . import fields as F
    row = conn.execute("SELECT id FROM characters WHERE campaign_id = ? AND name = ?", (campaign_id, NAME)).fetchone()
    vals = {k: F.to_db(F.CHARACTER[k], v) for k, v in CHARACTER.items()}
    vals["updated_at"] = now_iso()
    if row:
        if wildshape.is_shifted(conn, row["id"]):
            wildshape.revert(conn, row["id"], why="sheet refreshed")
        conn.execute(f"UPDATE characters SET {', '.join(k + ' = ?' for k in vals)} WHERE id = ?", (*vals.values(), row["id"]))
        char_id = row["id"]
    else:
        from .characters import default_character_values
        base = {k: F.to_db(F.CHARACTER[k], v) for k, v in default_character_values().items() if k not in vals}
        vals.update(base, uid=uuid.uuid4().hex, campaign_id=campaign_id, created_at=now_iso())
        cur = conn.execute(f"INSERT INTO characters ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", tuple(vals.values()))
        char_id = cur.lastrowid
    wildshape.give_forms(conn, char_id)
    return char_id


# ---- portrait ---------------------------------------------------------------------
PORTRAIT = "npc-zephyra-zm.png"


def draw(size=256):
    """Her initials, ZM, with two little pink antennas on top. Drawn 4x and shrunk so the edges are smooth."""
    import math
    import os
    from PIL import Image, ImageDraw, ImageFont
    big = size * 4
    S = big / 100.0
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def E(x, y, r, fill, outline=None, w=0):
        d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill, outline=outline, width=int(w * S) if w else 0)

    E(50, 50, 50, (42, 32, 30, 255))                         # the same dark disc as other initials tokens
    pink, pink_dark = (255, 120, 190, 255), (200, 60, 140, 255)
    for side in (-1, 1):                                      # antennas: curved stalks, round pink tips
        pts = []
        for k in range(21):
            t = k / 20
            pts.append(((50 + side * (6 + 16 * t + 3 * math.sin(t * 3.0))) * S, (51 - 34 * t + 6 * t * t) * S))
        d.line(pts, fill=pink_dark, width=int(3.2 * S), joint="curve")
        d.line(pts, fill=pink, width=int(2.0 * S), joint="curve")
        tx, ty = pts[-1][0] / S, pts[-1][1] / S
        E(tx, ty, 5.5, pink, pink_dark, .9)
        E(tx - 1.8, ty - 1.8, 1.7, (255, 225, 242, 255))      # shine
    font = None
    for name in ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), int(34 * S))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=int(34 * S))
    d.text((50 * S, 62 * S), "ZM", font=font, fill=(240, 226, 200, 255), anchor="mm")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def set_portrait(conn, char_id, upload_dir):
    import os
    draw().save(os.path.join(upload_dir, PORTRAIT), "PNG", optimize=True)
    conn.execute("UPDATE characters SET portrait = ?, updated_at = ? WHERE id = ?", (PORTRAIT, now_iso(), char_id))
