"""One monster stat block as the Monster Book stores it (app/monster_book.py, app/prison_monsters.py)."""


def _m(name, creature_type, cr, hp, ac, speed, abilities, attacks, traits="", senses="", languages="",
       resistances="", immunities="", vulnerabilities="", condition_immunities=""):
    keys = ("str", "dex", "con", "int", "wis", "cha")
    ab = dict(zip(keys, abilities))
    return {
        "name": name, "creature_type": creature_type, "cr": cr, "max_hp": hp, "ac": ac, "speed": speed,
        "initiative_mod": (ab["dex"] - 10) // 2, "abilities": ab, "attacks": "\n".join(attacks),
        "traits": "\n".join(traits) if isinstance(traits, (list, tuple)) else traits,
        "senses": senses, "languages": languages, "resistances": resistances, "immunities": immunities,
        "vulnerabilities": vulnerabilities, "condition_immunities": condition_immunities,
    }
