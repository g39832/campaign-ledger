"""One-click encounters: the party, a set of Monster Book enemies, and a
matching preset battle map with everyone already on it."""
from flask import Blueprint, jsonify, request

from . import fields as F
from .combat import _instance_names, _insert_enemy, _resort, encounter_state, mutate
from .db import get_db, new_uid, now_iso, tx
from .rules import derived

bp = Blueprint("encounter_presets", __name__, url_prefix="/api")

# (key, name, description, [(monster, count)], map preset)
PRESETS = [
    ("goblin-ambush", "Goblin ambush", "Goblins jump the party on a forest road, led by their boss.",
     [("Goblin", 4), ("Goblin Boss", 1)], "forest"),
    ("tavern-brawl", "Tavern brawl", "Thugs and bandits start trouble in the common room.",
     [("Thug", 2), ("Bandit", 3)], "tavern"),
    ("bandit-bridge", "Bandits at the bridge", "A bandit captain demands a toll at the river crossing.",
     [("Bandit Captain", 1), ("Bandit", 4)], "bridge"),
    ("crypt-dead", "Restless crypt", "Skeletons and zombies rise from the tombs; a ghoul lurks behind.",
     [("Skeleton", 3), ("Zombie", 2), ("Ghoul", 1)], "crypt"),
    ("wolf-pack", "Wolf pack", "Hungry wolves circle in the woods, a dire wolf at their head.",
     [("Wolf", 4), ("Dire Wolf", 1)], "forest"),
    ("cult-ritual", "Cult ritual", "Cultists chant around an altar while their fanatic leads the rite.",
     [("Cultist", 4), ("Cult Fanatic", 1)], "dungeon"),
    ("spider-cave", "Spider cave", "Giant spiders hunt in the dark tunnels.",
     [("Giant Spider", 2), ("Swarm of Rats", 1)], "cave"),
    ("arena-ogre", "Arena champion", "The crowd roars as an ogre and its handlers enter the pit.",
     [("Ogre", 1), ("Orc", 2)], "arena"),
    ("ship-raid", "Raid at sea", "Raiders storm the deck, a veteran at the front.",
     [("Veteran", 1), ("Bandit", 4)], "ship"),
    ("kobold-warren", "Kobold warren", "A swarm of kobolds defends their tunnels.",
     [("Kobold", 6), ("Giant Rat", 2)], "cave"),
]
BY_KEY = {p[0]: p for p in PRESETS}


def listing():
    return [{"key": k, "name": n, "description": d, "monsters": [{"name": m, "count": c} for m, c in mons], "map": mp}
            for k, n, d, mons, mp in PRESETS]


@bp.get("/encounter-presets")
def api_list():
    return jsonify({"presets": listing()})


@bp.post("/campaigns/<int:cid>/encounter-presets/<key>")
def api_use(cid, key):
    """Make the encounter, put the party and enemies in it, and make its map."""
    from .maps import create_map_from_preset, place_encounter_tokens
    from .monster_book import BY_NAME
    p = BY_KEY.get(key)
    if p is None:
        raise F.NotFound("No such preset")
    _, name, desc, monsters, map_key = p
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    ts = now_iso()
    with tx() as conn:
        eid = F.insert(conn, "encounters", F.ENCOUNTER, {"name": name, "notes": desc},
                       {"uid": new_uid(), "campaign_id": cid, "created_at": ts, "updated_at": ts})
        conn.execute("INSERT INTO combat_log (encounter_id, round, kind, message, created_at) VALUES (?, 0, 'system', ?, ?)",
                     (eid, f"Encounter “{name}” created from a preset", ts))

    def fill(ctx):
        added = []
        if data.get("party", True):
            for ch in ctx.conn.execute("SELECT * FROM characters WHERE campaign_id = ? AND archived = 0 AND kind = 'pc' "
                                       "ORDER BY name COLLATE NOCASE", (cid,)).fetchall():
                chd = F.decode_row(ch, F.CHARACTER)
                ctx.conn.execute(
                    """INSERT INTO combatants (uid, encounter_id, character_id, kind, name, init_mod, init_roll,
                       sort_order, max_hp, current_hp, ac, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (new_uid(), eid, ch["id"], ch["kind"], ch["name"], derived(chd)["initiative"], ch["initiative_roll"],
                     ctx.conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM combatants WHERE encounter_id = ?", (eid,)).fetchone()[0],
                     ch["max_hp"], ch["current_hp"], ch["ac"], now_iso()))
                added.append(ch["name"])
        for mon, count in monsters:
            block = F.validate_new(F.CREATURE, BY_NAME[mon])
            statblock = {k: block.get(k) for k in F.CREATURE if k != "name"}
            statblock["base_name"] = mon
            for n in _instance_names(ctx, mon, count):
                _insert_enemy(ctx, n, statblock, block["max_hp"], block["ac"], block["initiative_mod"])
                added.append(n)
        ctx.log("roster", f"Added {', '.join(added)}")
        if ctx.settings["auto_sort"]:
            _resort(ctx)
    mutate(eid, fill)
    with tx() as conn:
        map_id = create_map_from_preset(conn, cid, map_key, name=name, encounter_id=eid)
        place_encounter_tokens(conn, map_id)
    return jsonify({"encounter_id": eid, "map_id": map_id, "encounter": encounter_state(eid)}), 201
