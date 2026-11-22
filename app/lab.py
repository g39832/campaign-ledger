"""Stocking the laboratory: five floors that slowly get harder on the way up to the head researcher.

- Each floor: some rooms hold enemies (hidden until a hero walks in or sees them, so the usual fight
  starts). Higher floors have more rooms with enemies, more of them, and tougher ones (ROOMS_WITH_FOES).
- The lift room at the end of floors 1-4 is guarded by that floor's strongest enemies.
- Three supply lockers a floor, with only healing items and lab credits (app/loot.py "lab").
- The top floor (5): the Director (the boss, head of Project Chimera) and one hazmat trooper, and behind
  them the Director's Safe: a single rare magic item from the DM's list, the only magic item in the lab.
- 2026-11-15 (Grayson): fewer enemies on every floor (about 3, 4, 4, 5, 4 with the boss).
"""
import random

from .chests import add_chest
from .dungeon import LAB_FLOORS
from .prison import _cells_of, ensure_creatures
from .prison_monsters import LAB_NAMES

# floor -> (who turns up in its rooms, who guards the lift room / the boss room)
# and how many rooms on the way have enemies, and how many in each (so every floor is harder than the last)
ROOMS_WITH_FOES = {1: (1, 1), 2: (2, 1), 3: (2, 1), 4: (3, 1), 5: (2, 1)}
FLOORS = {
    1: (["Escaped Test Subject", "Escaped Test Subject", "Lab Assistant Drone"],
        [("Escaped Test Subject", 1), ("Lab Assistant Drone", 1)]),
    2: (["Escaped Test Subject", "Lab Assistant Drone", "Hazmat Trooper"],
        [("Hazmat Trooper", 1), ("Lab Assistant Drone", 1)]),
    3: (["Hazmat Trooper", "Escaped Test Subject", "Bio-Ooze", "Lab Assistant Drone"],
        [("Bio-Ooze", 1), ("Hazmat Trooper", 1)]),
    4: (["Hazmat Trooper", "Bio-Ooze", "Chimera Specimen", "Escaped Test Subject"],
        [("Chimera Specimen", 1), ("Hazmat Trooper", 1)]),
    5: (["Hazmat Trooper", "Bio-Ooze", "Chimera Specimen"],
        [("The Director", 1), ("Hazmat Trooper", 1)]),
}
CHESTS_PER_FLOOR = 3


def furnish(conn, map_id, foes_only=False):
    """foes_only: put a floor's enemies down again (its lockers and papers stay where they are)."""
    from . import maps as M
    m = M.map_dict(M._map_row(conn, map_id))
    d = m.get("dungeon") or {}
    if d.get("theme") != "lab":
        return
    level = max(1, min(int(d.get("level") or 1), LAB_FLOORS))
    rnd = random.Random(int(d.get("seed") or 1) * 37 + level)
    lib = ensure_creatures(conn, m["campaign_id"], LAB_NAMES)
    used = set()  # squares with a chest or a monster on them
    if foes_only:
        used |= {(r["x"], r["y"]) for r in conn.execute("SELECT x, y FROM chests WHERE map_id = ?", (map_id,))}
        for t in conn.execute("SELECT x, y, size FROM map_tokens WHERE map_id = ?", (map_id,)):
            used |= {(int(round(t["x"])) + a, int(round(t["y"])) + b) for a in range(t["size"] or 1) for b in range(t["size"] or 1)}

    def open_cells(room, size=1):
        x0, y0, x1, y1 = room["box"]
        out = []
        for x, y in _cells_of(room["box"]):
            sq = [(x + dx, y + dy) for dx in range(size) for dy in range(size)]
            if all(m["terrain"].get(f"{a},{b}") not in M.BLOCKING and m["terrain"].get(f"{a},{b}") != "stairs" and (a, b) not in used
                   and x0 <= a <= x1 and y0 <= b <= y1 for a, b in sq):
                out.append((x, y))
        return out

    def chest(kind, room):
        spots = open_cells(room)
        if not spots:
            return
        x0, y0, x1, y1 = room["box"]
        spots.sort(key=lambda p: (p[0] not in (x0, x1) and p[1] not in (y0, y1), rnd.random()))  # against a wall
        x, y = spots[0]
        used.add((x, y))
        add_chest(conn, map_id, kind, x, y, None, False, "", "placed", None, rnd.randrange(1, 2 ** 31))

    def foe(name, room, n=1):
        block, cid = lib[name]
        size = 2 if str(block.get("creature_type") or "").startswith("Large") else 1
        cx, cy = (room["box"][0] + room["box"][2]) / 2, (room["box"][1] + room["box"][3]) / 2
        for _ in range(n):
            spots = open_cells(room, size)
            if not spots:
                return
            spots.sort(key=lambda p: abs(p[0] - cx) + abs(p[1] - cy) + rnd.random() * 2)
            x, y = spots[0]
            M.add_monsters(conn, m, block, name, cid, 1, x, y, hidden=True)
            for dx in range(size):
                for dy in range(size):
                    used.add((x + dx, y + dy))

    rooms = d["rooms"]
    boss = next(r for r in rooms if r["kind"] == "boss")
    middle = [r for r in rooms if r["kind"] not in ("start", "boss")]
    pool, guards = FLOORS[level]
    # the rooms along the way: more of them have enemies, and more enemies, the higher the floor
    # (taking turns through the floor's list, so each floor gets its mix rather than a lucky run)
    count, each = ROOMS_WITH_FOES[level]
    order = pool[:]
    rnd.shuffle(order)
    picked = rnd.sample(middle, min(count, len(middle)))
    k = 0
    for r in picked:
        for _ in range(each):
            foe(order[k % len(order)], r)
            k += 1
    # the lift room (or the head researcher's lab)
    for name, n in guards:
        foe(name, boss, n)
    if foes_only:
        M._bump(conn, map_id)
        return
    # three lockers of healing items and money, each in a different room
    spots = middle[:] if len(middle) >= CHESTS_PER_FLOOR else middle + [boss]
    rnd.shuffle(spots)
    for r in spots[:CHESTS_PER_FLOOR]:
        chest("lab", r)
    if level >= LAB_FLOORS:  # the only magic item in the lab
        chest("labprize", boss)
    from .lab_papers import place
    place(conn, map_id)  # the floor's loose papers (clues, and the station coordinates on top)
    M._bump(conn, map_id)
