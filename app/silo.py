"""Stocking the missile silo, and its ending (2026-11-16, Grayson's design).

Levels 1-3 (app/silo_layout.py): Steven Voss's machines in some rooms and guarding the freight lift
(tougher each level down), three supply crates a level, and a couple of loose papers that tell the story.

Level 4, the launch bay:
- Ironclad Harlan: the giant robot Steven rebuilt in his son Harlan's image (the boss), two sentry
  drones, and two guard automatons at the checkpoint.
- Steven Voss on his gantry by his escape lift. He does NOT fight: he's a story token, not in the fight.
- The choice, made by the players on their phones (or by the DM on the map page):
    * turn all three LAUNCH ABORT keys (one under each missile; stand next to it, one action each):
      the missiles power down, and Steven gets away up his escape lift;
    * or go after Steven (stand next to his escape lift and tap Stop him): they catch him, and the
      missiles launch.
- A launch countdown (LAUNCH_ROUNDS) starts when the fight with the robot starts. If it runs out with
  neither done, the missiles launch AND Steven gets away. The DM can add rounds or decide it by hand.
Every outcome pops up a handout on everyone's screen and is written to the fight log.
"""
import json
import random

from .db import new_uid, now_iso
from .silo_layout import ESCAPE_AT, ROBOT_AT, SILO_LEVELS, STEVEN_AT, TUBES, abort_spots

LAUNCH_ROUNDS = 8
# What the missiles are aimed at, for the handouts. Empty: the handouts don't say (the DM tells the table).
TARGET = ""
ROBOT = "Ironclad Harlan"

# level -> (who turns up in the rooms on the way, who guards the freight lift)
FLOORS = {
    1: (["Silo Guard Automaton", "Voss Sentry Drone"], [("Silo Guard Automaton", 1), ("Voss Sentry Drone", 1)]),
    2: (["Silo Guard Automaton", "Voss Loyalist Engineer", "Voss Sentry Drone", "Point-Defense Turret"],
        [("Point-Defense Turret", 1), ("Voss Loyalist Engineer", 1), ("Voss Sentry Drone", 1)]),
    3: (["Ironclad Walker", "Voss Loyalist Engineer", "Silo Guard Automaton", "Point-Defense Turret"],
        [("Ironclad Walker", 1), ("Silo Guard Automaton", 1)]),
}
ROOMS_WITH_FOES = {1: 2, 2: 2, 3: 3}
CRATES_PER_LEVEL = 3

PAPERS = {
    1: [("Shift roster",
         "SILO 9 — VOSS INDUSTRIES\n\nAll human staff OFF SITE by order of S. Voss.\nThe automatons hold every level.\n"
         "Engineers (loyal list only) report to the launch bay.\n\nNOBODY goes near Unit H unless Mr. Voss is there."),
        ("Delivery slip",
         "DELIVERED TO: launch bay, level 4\n\n1 x face casting, iron, made from the photograph supplied\n"
         "1 x shield, recovered, to be welded to the left arm\n\nSigned for: S. Voss\n\n"
         "(In pencil, underneath:) make the jaw stubborn. like his.")],
    2: [("Engineer's diary",
         "Day 40. The boss talks to it. Not the way you talk to a machine. He tells it about fishing trips.\n\n"
         "Day 41. It answered. A recording, but it answered. \"Dad? Is it time yet?\" Half the crew walked out that night.\n\n"
         "Day 42. The rest of us got a raise."),
        ("Fuel stage checklist",
         "STAGE TWO FUEL — ALL THREE BIRDS — FULL\n\nGuidance: target locked.\nDo not ask what it is. — S.V.")],
    3: [("Maintenance tag: Unit H",
         "UNIT H — DO NOT POWER DOWN\n\nFace plate refitted three times. Mr. Voss says the eyes are \"still wrong\".\n\n"
         "It runs hot after the earth-shatter routine (copied from old footage of the original). "
         "Below half power it stops holding back. Stay clear."),
        ("Launch procedure, page 2",
         "IF THE LAUNCH MUST BE STOPPED\n\nThree abort keys, one under each tube. ALL THREE must be turned.\n"
         "Leave one and the launch goes ahead.\n\nThe gantry lift runs straight to the surface. It leaves when Mr. Voss says it leaves.")],
    4: [("Note pinned to the door",
         "To whoever comes through,\n\nI know who you are. I know what happened to my son.\n"
         "He's in there. I made him again.\n\nTurn the keys if you like. I'll be gone by then.\n"
         "Or come for me, and watch the sky.\n\n— S. Voss")],
}


def _note(title, text, rnd):
    return {"id": "%08x" % rnd.getrandbits(32), "name": title, "qty": 1, "rarity": "common", "type": "note", "weight": 0, "desc": text}


def _maps():
    from . import maps as M
    return M


def _save_info(conn, map_id, d):
    conn.execute("UPDATE maps SET dungeon = ? WHERE id = ?", (json.dumps(d), map_id))


def furnish(conn, map_id, foes_only=False):
    from .chests import add_chest
    from .prison import _cells_of, ensure_creatures
    from .prison_monsters import SILO_NAMES
    M = _maps()
    m = M.map_dict(M._map_row(conn, map_id))
    d = m.get("dungeon") or {}
    if d.get("theme") != "silo":
        return
    level = max(1, min(int(d.get("level") or 1), SILO_LEVELS))
    rnd = random.Random(int(d.get("seed") or 1) * 41 + level)
    lib = ensure_creatures(conn, m["campaign_id"], SILO_NAMES)
    used = {(r["x"], r["y"]) for r in conn.execute("SELECT x, y FROM chests WHERE map_id = ?", (map_id,))}
    for t in conn.execute("SELECT x, y, size FROM map_tokens WHERE map_id = ?", (map_id,)):
        used |= {(int(round(t["x"])) + a, int(round(t["y"])) + b) for a in range(t["size"] or 1) for b in range(t["size"] or 1)}
    if level >= SILO_LEVELS:  # the special squares on the last level stay clear
        used |= set(abort_spots()) | {tuple(STEVEN_AT), tuple(ESCAPE_AT)}
    sx, sy = d.get("start") or (-1, -1)
    used.add((sx, sy))

    def open_cells(room, size=1):
        x0, y0, x1, y1 = room["box"]
        out = []
        for x, y in _cells_of(room["box"]):
            sq = [(x + dx, y + dy) for dx in range(size) for dy in range(size)]
            if all(m["terrain"].get(f"{a},{b}") not in M.BLOCKING and m["terrain"].get(f"{a},{b}") not in ("lift", "escape")
                   and (a, b) not in used and x0 <= a <= x1 and y0 <= b <= y1 for a, b in sq):
                out.append((x, y))
        return out

    def foe(name, room, at=None):
        block, cid = lib[name]
        size = {"Large": 2, "Huge": 3, "Gargantuan": 4}.get(str(block.get("creature_type") or "").split(" ")[0], 1)
        cx, cy = at or ((room["box"][0] + room["box"][2]) / 2, (room["box"][1] + room["box"][3]) / 2)
        spots = open_cells(room, size)
        if not spots:
            return
        spots.sort(key=lambda p: abs(p[0] - cx) + abs(p[1] - cy) + (0 if at else rnd.random() * 2))
        x, y = spots[0]
        M.add_monsters(conn, m, block, name, cid, 1, x, y, hidden=True)
        used.update((x + dx, y + dy) for dx in range(size) for dy in range(size))

    def chest(kind, room, label=""):
        spots = open_cells(room)
        if not spots:
            return
        x0, y0, x1, y1 = room["box"]
        spots.sort(key=lambda p: (p[0] not in (x0, x1) and p[1] not in (y0, y1), rnd.random()))
        x, y = spots[0]
        used.add((x, y))
        add_chest(conn, map_id, kind, x, y, None, False, label, "placed", None, rnd.randrange(1, 2 ** 31))

    rooms = d["rooms"]
    boss = next(r for r in rooms if r["kind"] == "boss")
    if level >= SILO_LEVELS:
        check = next(r for r in rooms if r["name"] == "Security checkpoint")
        foe(ROBOT, boss, ROBOT_AT)
        foe("Voss Sentry Drone", boss, (TUBES[0][0], 12))
        foe("Voss Sentry Drone", boss, (TUBES[2][0], 12))
        foe("Silo Guard Automaton", check)
        foe("Silo Guard Automaton", check)
        if foes_only:
            M._bump(conn, map_id)
            return
        chest("lab", check, "Silo Supply Crate")
        _papers(conn, map_id, level, [check], used, m, rnd)
        for i, (x, y) in enumerate(abort_spots()):
            add_chest(conn, map_id, "abort", x, y, None, False, f"Launch abort key {i + 1}", "placed", [], 1)
        add_chest(conn, map_id, "escape", ESCAPE_AT[0], ESCAPE_AT[1], None, False, "Steven's escape lift", "placed", [], 1)
        _steven_token(conn, map_id)
        m = M.map_dict(M._map_row(conn, map_id))
        d = m["dungeon"]
        d["silo"] = {"rounds": LAUNCH_ROUNDS, "ticks": 0, "fight": None, "outcome": None}
        _save_info(conn, map_id, d)
        M._bump(conn, map_id)
        return
    middle = [r for r in rooms if r["kind"] == "room" and not r["name"].startswith("Shaft rim")]
    pool, guards = FLOORS[level]
    order = pool[:]
    rnd.shuffle(order)
    for k, r in enumerate(rnd.sample(middle, min(ROOMS_WITH_FOES[level], len(middle)))):
        foe(order[k % len(order)], r)
    for name, n in guards:
        for _ in range(n):
            foe(name, boss)
    if foes_only:
        M._bump(conn, map_id)
        return
    spots = middle[:]
    rnd.shuffle(spots)
    for r in spots[:CRATES_PER_LEVEL]:
        chest("lab", r, "Silo Supply Crate")
    _papers(conn, map_id, level, [r for r in middle if r not in spots[:CRATES_PER_LEVEL]] or middle, used, m, rnd)
    M._bump(conn, map_id)


def _papers(conn, map_id, level, rooms, used, m, rnd):
    from .chests import add_chest
    from .prison import _cells_of
    M = _maps()
    for i, (title, text) in enumerate(PAPERS.get(level, [])):
        room = rooms[i % len(rooms)]
        spots = [(x, y) for x, y in _cells_of(room["box"])
                 if m["terrain"].get(f"{x},{y}") not in M.BLOCKING and (x, y) not in used]
        if not spots:
            continue
        x, y = rnd.choice(spots)
        used.add((x, y))
        add_chest(conn, map_id, "papers", x, y, "", False, title, "placed", [_note(title, text, rnd)], rnd.randrange(1, 2 ** 31))


def _steven_token(conn, map_id):
    """Steven on his gantry: a token with his name, not in the fight."""
    if conn.execute("SELECT 1 FROM map_tokens WHERE map_id = ? AND label = 'Steven Voss'", (map_id,)).fetchone():
        return
    ts = now_iso()
    conn.execute("INSERT INTO map_tokens (uid, map_id, kind, label, x, y, size, color, hidden, notes, created_at, updated_at) "
                 "VALUES (?, ?, 'npc', 'Steven Voss', ?, ?, 1, '#e0a020', 0, ?, ?, ?)",
                 (new_uid(), map_id, STEVEN_AT[0], STEVEN_AT[1],
                  "Doesn't fight. Stands by his escape lift and watches his son's robot.", ts, ts))


# ---- the ending --------------------------------------------------------------------------------------

def _aimed():
    return f" towards {TARGET}" if TARGET else ""


OUTCOMES = {
    "aborted": ("The missiles are down",
                "The third key turns. Every light in the launch bay goes from red to dead grey, and the three missiles "
                "power down in their tubes with a long falling whine.\n\n"
                "Up on the gantry, Steven Voss doesn't even look at you. He looks at the robot with his son's face, "
                "says something nobody can hear, and steps into his escape lift. The doors close. He's gone.\n\n"
                "The missiles will never fly. Steven Voss got away."),
    "caught": ("The missiles launch",
               "You reach the gantry and drag Steven Voss away from his escape lift. He doesn't fight you. He just smiles.\n\n"
               "Behind you the launch bay roars. The tubes blaze white, the floor bucks, and three missiles tear up the "
               "shaft and into the sky{aimed}.\n\n"
               "You have Steven Voss. The missiles are gone."),
    "timeout": ("Too late",
                "The countdown hits zero. The tubes blaze white, the floor bucks, and three missiles tear up the shaft "
                "and into the sky{aimed}.\n\n"
                "When the smoke clears, the gantry is empty. Steven Voss went up his escape lift while you fought.\n\n"
                "The missiles launched, and Steven Voss got away."),
}


def info(m):
    d = m.get("dungeon") or {}
    return d.get("silo") if d.get("theme") == "silo" else None


def public(conn, m):
    """What the players see: the countdown, the keys turned, and how it ended."""
    s = info(m)
    if not s:
        return None
    keys = conn.execute("SELECT COUNT(*) AS n, SUM(opened) AS done FROM chests WHERE map_id = ? AND kind = 'abort'", (m["id"],)).fetchone()
    on = bool(s.get("fight")) or _robot_fighting(conn, m)
    return {"rounds_left": max(0, s["rounds"] - s["ticks"]) if on else None, "rounds": s["rounds"],
            "outcome": s.get("outcome"), "keys": int(keys["done"] or 0), "keys_total": int(keys["n"] or 0)}


def _robot_fighting(conn, m):
    """The robot is in this map's running fight (round 1, before the countdown's first tick)."""
    if not m.get("encounter_id"):
        return False
    row = conn.execute("SELECT 1 FROM encounters e JOIN combatants c ON c.encounter_id = e.id WHERE e.id = ? AND e.status = 'active' "
                       "AND c.name LIKE ?", (m["encounter_id"], ROBOT + "%")).fetchone()
    return row is not None


def _handout_all(conn, campaign_id, title, body):
    ts = now_iso()
    conn.execute("INSERT INTO handouts (uid, campaign_id, title, body, image, to_characters, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (new_uid(), campaign_id, title, body, None, None, ts, ts))


def _log(conn, m, text):
    if m.get("encounter_id"):
        enc = conn.execute("SELECT round, status FROM encounters WHERE id = ?", (m["encounter_id"],)).fetchone()
        if enc and enc["status"] != "ended":
            conn.execute("INSERT INTO combat_log (encounter_id, round, kind, message, created_at) VALUES (?, ?, 'system', ?, ?)",
                         (m["encounter_id"], enc["round"], text, now_iso()))
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), m["encounter_id"]))


def decide(conn, map_id, outcome, by="The DM"):
    """aborted | caught | timeout. The map changes (missiles gone, Steven gone), everyone gets the handout."""
    M = _maps()
    m = M.map_dict(M._map_row(conn, map_id))
    s = info(m)
    if not s:
        from . import fields as F
        raise F.ApiError("That isn't the silo's launch bay")
    if s.get("outcome"):
        from . import fields as F
        raise F.ApiError("It's already over: " + OUTCOMES[s["outcome"]][0].lower(), status=409)
    d = m["dungeon"]
    d["silo"] = dict(s, outcome=outcome, by=by, at=now_iso())
    _save_info(conn, map_id, d)
    t = m["terrain"]
    if outcome in ("caught", "timeout"):  # the tubes stand empty and scorched
        for k, v in list(t.items()):
            if v == "missile":
                t[k] = "shaft"
        conn.execute("UPDATE maps SET terrain = ? WHERE id = ?", (json.dumps(t), map_id))
    if outcome in ("aborted", "timeout"):  # Steven goes up his lift
        conn.execute("DELETE FROM map_tokens WHERE map_id = ? AND label = 'Steven Voss'", (map_id,))
    conn.execute("UPDATE chests SET opened = 1, opened_by = CASE WHEN opened_by = '' THEN ? ELSE opened_by END, opened_at = COALESCE(opened_at, ?), updated_at = ? "
                 "WHERE map_id = ? AND kind = 'escape'", (by, now_iso(), now_iso(), map_id))
    title, body = OUTCOMES[outcome]
    _handout_all(conn, m["campaign_id"], title, body.format(aimed=_aimed()))
    _log(conn, m, f"{title}! ({by})")
    M._bump(conn, map_id)
    return title


def reset(conn, map_id):
    """The DM's undo: missiles back, Steven back, keys unturned, countdown from the start."""
    M = _maps()
    m = M.map_dict(M._map_row(conn, map_id))
    s = info(m)
    if not s:
        return
    t = m["terrain"]
    for cx, cy in TUBES:
        for x in range(cx - 1, cx + 2):
            for y in range(cy - 1, cy + 2):
                t[f"{x},{y}"] = "missile"
    conn.execute("UPDATE maps SET terrain = ? WHERE id = ?", (json.dumps(t), map_id))
    conn.execute("UPDATE chests SET opened = 0, opened_by = '', opened_at = NULL, updated_at = ? WHERE map_id = ? AND kind IN ('abort', 'escape')",
                 (now_iso(), map_id))
    _steven_token(conn, map_id)
    d = m["dungeon"]
    d["silo"] = {"rounds": LAUNCH_ROUNDS, "ticks": 0, "fight": None, "outcome": None}
    _save_info(conn, map_id, d)
    M._bump(conn, map_id)


def more_rounds(conn, map_id, n=2):
    M = _maps()
    m = M.map_dict(M._map_row(conn, map_id))
    s = info(m)
    if not s or s.get("outcome"):
        return
    d = m["dungeon"]
    d["silo"] = dict(s, rounds=max(1, s["rounds"] + n))
    _save_info(conn, map_id, d)
    _log(conn, m, f"The launch countdown changes: {max(0, d['silo']['rounds'] - s['ticks'])} rounds left")
    M._bump(conn, map_id)


def use(conn, m, r, ch):
    """A hero next to an abort key or Steven's lift taps it (app/chests.py api_play_open has checked they're next to it).
    Called before the chest is marked open: refuses once it's all over."""
    s = info(m)
    if not s:
        return
    if s.get("outcome"):
        from . import fields as F
        raise F.ApiError("It's over: " + OUTCOMES[s["outcome"]][0].lower(), status=409)


def after_use(conn, m, r, ch):
    """After the key was turned (the chest marked open): the third key, or reaching Steven, ends it."""
    s = info(m)
    if not s or s.get("outcome"):
        return
    if r["kind"] == "escape":
        decide(conn, m["id"], "caught", ch["name"])
        return
    left = conn.execute("SELECT COUNT(*) FROM chests WHERE map_id = ? AND kind = 'abort' AND opened = 0", (m["id"],)).fetchone()[0]
    if left == 0:
        decide(conn, m["id"], "aborted", ch["name"])
    else:
        _log(conn, m, f"{ch['name']} turns a launch abort key ({3 - left if left <= 3 else '?'} of 3)")


def round_begins(ctx):
    """combat.next_turn, a new round: the launch countdown (it starts when the fight with the robot does)."""
    conn = ctx.conn
    row = conn.execute("SELECT * FROM maps WHERE encounter_id = ? AND dungeon LIKE '%\"silo\"%'", (ctx.enc["id"],)).fetchone()
    if row is None:
        return
    M = _maps()
    m = M.map_dict(row)
    s = info(m)
    if not s or s.get("outcome"):
        return
    if not any(c["name"].startswith(ROBOT) for c in ctx.combatants()):
        return
    d = m["dungeon"]
    if s.get("fight") != ctx.enc["id"]:  # the robot's fight: the countdown starts now (this is its round 2)
        s = dict(s, fight=ctx.enc["id"], ticks=0)
    s = dict(s, ticks=s["ticks"] + 1)
    d["silo"] = s
    _save_info(conn, m["id"], d)
    left = s["rounds"] - s["ticks"]
    if left <= 0:
        decide(conn, m["id"], "timeout", "the countdown")
        return
    ctx.log("system", f"LAUNCH IN {left} ROUND{'S' if left != 1 else ''}")
    M._bump(conn, m["id"])


