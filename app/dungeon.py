"""Made-up maps: a new layout every time (a dungeon, a cave or a prison), painted with terrain.

Every one has a start (where the party comes in), rooms with names, a boss room, and stairs
down inside the boss room. When a hero steps on the stairs (and no fight is running on the
map), the next level is made and shown to everyone, with the party standing at its start.

    generate(theme, seed, level) -> {name, cols, rows, bg_color, terrain, rooms, start, exit}
    rooms: [{"name", "kind": "start" | "room" | "boss" | "cell" | ..., "box": [x0, y0, x1, y1]}]
"""
import random
from collections import deque

THEMES = {
    "dungeon": {"name": "Dungeon", "floor": "stone", "bg": "#2b2622", "about": "Stone rooms joined by corridors, with doors, traps and a boss's hall."},
    "cave": {"name": "Cave", "floor": "sand", "bg": "#3a332b", "about": "Winding caverns with pools and loose rock, ending in a great cavern."},
    "prison": {"name": "Prison", "floor": "stone", "bg": "#26231f", "about": "A gatehouse, cell blocks off long corridors, guard rooms, and the warden's office."},
}
# what you can't walk through (doors and rubble you can)
SOLID = {"wall", "pit", "water", "lava", "tree", "table", "rock"}
ROOM_NAMES = ["Guard post", "Storeroom", "Shrine", "Barracks", "Library", "Armory", "Crypt", "Kitchen", "Well room", "Trophy hall",
              "Torture chamber", "Old chapel", "Workshop", "Collapsed hall"]
BOSS_NAMES = {"dungeon": ["The Throne Room", "The Bone Hall", "The Black Altar"], "cave": ["The Great Cavern", "The Lair", "The Deep Pool"],
              "prison": ["The Warden's Office", "The Execution Hall", "The Deep Cells"]}


def _k(x, y):
    return f"{x},{y}"


def _fill(t, x0, y0, x1, y1, kind):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            t[_k(x, y)] = kind


def walkable(t, x, y, cols, rows):
    return 0 <= x < cols and 0 <= y < rows and t.get(_k(x, y)) not in SOLID


def path_len(t, a, b, cols, rows):
    """Steps from a to b walking on open ground (diagonals allowed), or None if there's no way."""
    seen, q = {tuple(a): 0}, deque([tuple(a)])
    while q:
        x, y = q.popleft()
        if (x, y) == tuple(b):
            return seen[(x, y)]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and n not in seen and walkable(t, *n, cols, rows):
                    seen[n] = seen[(x, y)] + 1
                    q.append(n)
    return None


def _corridor(t, a, b, floor, rnd):
    """An L-shaped corridor between two points (keeps doors that are already there)."""
    (x0, y0), (x1, y1) = a, b
    if rnd.random() < 0.5:
        pts = [(x, y0) for x in range(min(x0, x1), max(x0, x1) + 1)] + [(x1, y) for y in range(min(y0, y1), max(y0, y1) + 1)]
    else:
        pts = [(x0, y) for y in range(min(y0, y1), max(y0, y1) + 1)] + [(x, y1) for x in range(min(x0, x1), max(x0, x1) + 1)]
    for x, y in pts:
        if t.get(_k(x, y)) in ("wall", None):
            t[_k(x, y)] = floor


def _center(box):
    x0, y0, x1, y1 = box
    return ((x0 + x1) // 2, (y0 + y1) // 2)


def _doors(t, box, floor):
    """Where a corridor runs into a room's edge, put a door in the gap in its wall ring."""
    x0, y0, x1, y1 = box
    ring = [(x, y0 - 1) for x in range(x0, x1 + 1)] + [(x, y1 + 1) for x in range(x0, x1 + 1)] + \
           [(x0 - 1, y) for y in range(y0, y1 + 1)] + [(x1 + 1, y) for y in range(y0, y1 + 1)]
    for x, y in ring:
        if t.get(_k(x, y)) == floor:
            t[_k(x, y)] = "door"


# ---- the layouts -----------------------------------------------------------------------------

def _rooms_and_corridors(rnd, cols, rows, floor, count):
    """Rooms placed at random (not touching), joined in a chain from left to right plus a loop or two."""
    t = {}
    _fill(t, 0, 0, cols - 1, rows - 1, "wall")
    boxes = []
    for _ in range(400):
        if len(boxes) >= count:
            break
        w, h = rnd.randint(5, 9), rnd.randint(4, 7)
        x0, y0 = rnd.randint(2, cols - w - 3), rnd.randint(2, rows - h - 3)
        box = (x0, y0, x0 + w - 1, y0 + h - 1)
        if all(box[0] > b[2] + 2 or box[2] < b[0] - 2 or box[1] > b[3] + 2 or box[3] < b[1] - 2 for b in boxes):
            boxes.append(box)
    boxes.sort(key=lambda b: (b[0], b[1]))
    for b in boxes:
        _fill(t, *b, floor)
    for a, b in zip(boxes, boxes[1:]):
        _corridor(t, _center(a), _center(b), floor, rnd)
    for _ in range(rnd.randint(1, 2)):  # a loop or two, so there's more than one way round
        a, b = rnd.sample(boxes, 2)
        _corridor(t, _center(a), _center(b), floor, rnd)
    for b in boxes:
        _fill(t, *b, floor)  # corridors don't cut furniture into rooms
        _doors(t, b, floor)
    return t, boxes


def _dungeon(rnd, cols, rows, level):
    floor = "stone"
    t, boxes = _rooms_and_corridors(rnd, cols, rows, floor, 8)
    names = rnd.sample(ROOM_NAMES, len(boxes))
    rooms = [{"name": n, "kind": "room", "box": list(b)} for n, b in zip(names, boxes)]
    for r in rooms[1:-1]:  # a few things in the rooms: a pit trap, rubble, a pool, a table
        x0, y0, x1, y1 = r["box"]
        what = rnd.choice(["pit", "rubble", "water", "table", "difficult", None])
        if what and x1 - x0 >= 4 and y1 - y0 >= 3:
            x, y = rnd.randint(x0 + 1, x1 - 2), rnd.randint(y0 + 1, y1 - 2)
            _fill(t, x, y, x + 1, y + (0 if what == "table" else 1), what)
    return t, rooms, floor


def _cave(rnd, cols, rows, level):
    floor = "sand"
    solid = [[rnd.random() < 0.52 for _ in range(cols)] for _ in range(rows)]
    for _ in range(5):
        nxt = []
        for y in range(rows):
            row = []
            for x in range(cols):
                n = sum(1 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx or dy)
                        and (not (0 <= x + dx < cols and 0 <= y + dy < rows) or solid[y + dy][x + dx]))
                row.append(n >= 5 or (n >= 4 and solid[y][x]))
            nxt.append(row)
        solid = nxt
    t = {}
    for y in range(rows):
        for x in range(cols):
            t[_k(x, y)] = "wall" if solid[y][x] or x in (0, cols - 1) or y in (0, rows - 1) else floor
    # caverns: an entrance on the left, a great cavern on the right, a few in between
    boxes = [(2, rows // 2 - 3, 7, rows // 2 + 2)]
    for _ in range(4):
        w, h = rnd.randint(4, 7), rnd.randint(4, 6)
        x0 = rnd.randint(10, cols - 20)
        y0 = rnd.randint(2, rows - h - 3)
        boxes.append((x0, y0, x0 + w - 1, y0 + h - 1))
    boxes.sort(key=lambda b: b[0])
    boxes.append((cols - 13, rows // 2 - 5, cols - 3, rows // 2 + 4))
    for b in boxes:
        _fill(t, *b, floor)
    for a, b in zip(boxes, boxes[1:]):
        _corridor(t, _center(a), _center(b), floor, rnd)
        _corridor(t, (_center(a)[0], _center(a)[1] + 1), (_center(b)[0], _center(b)[1] + 1), floor, rnd)  # two wide
    for _ in range(int(cols * rows * 0.02)):  # pools, loose rock, rubble
        x, y = rnd.randrange(1, cols - 1), rnd.randrange(1, rows - 1)
        if t[_k(x, y)] == floor:
            t[_k(x, y)] = rnd.choice(["water", "rubble", "difficult", "rubble"])
    names = ["Cave mouth"] + rnd.sample(["Dripping hollow", "Bat roost", "Glowing grotto", "Fungus garden", "Bone pile", "Echo chamber", "Crystal hall"], len(boxes) - 2) + ["Great cavern"]
    rooms = [{"name": n, "kind": "room", "box": list(b)} for n, b in zip(names, boxes)]
    return t, rooms, floor


def _prison(rnd, cols, rows, level):
    """A gatehouse on the left, a passage up and down, and two long cell-block corridors with
    cells on both sides (now and then a guard room, mess hall or interrogation room instead)."""
    floor = "stone"
    t = {}
    _fill(t, 0, 0, cols - 1, rows - 1, "wall")
    rooms = []
    tiers = (8, 19)  # corridor rows (two squares wide each)
    gate = (2, 11, 6, 16)
    _fill(t, *gate, floor)
    rooms.append({"name": "Gatehouse", "kind": "room", "box": list(gate)})
    _fill(t, 8, tiers[0], 9, tiers[1] + 1, floor)          # the passage joining the blocks
    t[_k(7, 13)] = t[_k(7, 14)] = "door"
    _fill(t, 7, 13, 7, 14, "door")
    for ty in tiers:
        _fill(t, 10, ty, cols - 14, ty + 1, floor)
    cells = 0
    for bi, ty in enumerate(tiers):
        for side in ("up", "down"):
            y0, y1, dy = (ty - 4, ty - 2, ty - 1) if side == "up" else (ty + 3, ty + 5, ty + 2)
            x = 11
            while x + 2 <= cols - 16:
                if rnd.random() < 0.18 and x + 6 <= cols - 16:  # a room instead of two cells
                    box = (x, y0, x + 6, y1)
                    _fill(t, *box, floor)
                    t[_k(x + 3, dy)] = "door"
                    kind = rnd.choice(["Guard room", "Mess hall", "Interrogation room", "Laundry", "Infirmary", "Storeroom"])
                    if kind == "Mess hall":
                        _fill(t, x + 1, (y0 + y1) // 2, x + 5, (y0 + y1) // 2, "table")
                    elif kind == "Interrogation room":
                        t[_k(x + 3, (y0 + y1) // 2)] = "table"
                        t[_k(x + 1, y0 if side == "up" else y1)] = "pit"
                    elif kind in ("Guard room", "Storeroom"):
                        _fill(t, x + 1, y0 if side == "up" else y1, x + 2, y0 if side == "up" else y1, "table" if kind == "Guard room" else "rubble")
                    rooms.append({"name": kind, "kind": "room", "box": list(box)})
                    x += 8
                    continue
                box = (x, y0, x + 2, y1)
                _fill(t, *box, floor)
                t[_k(x + 1, dy)] = "door"
                if rnd.random() < 0.4:
                    t[_k(x + rnd.randint(0, 2), y0 if side == "up" else y1)] = "rubble"  # a cot, a bucket
                cells += 1
                rooms.append({"name": f"Cell {cells}", "kind": "cell", "box": list(box)})
                x += 4
    return t, rooms, floor


LAYOUTS = {"dungeon": _dungeon, "cave": _cave, "prison": _prison}


def _boss_room(t, rooms, theme, rnd, cols, rows, floor, start):
    """The boss room: for a prison, the warden's office at the far end of the corridor; otherwise
    the room farthest from the start, made big. Pillars, a dais, and the stairs down at the back."""
    mid = rows // 2
    if theme == "prison":
        box = (cols - 12, 8, cols - 3, 20)
        _fill(t, *box, floor)
        for y in (8, 9, 19, 20):
            t[_k(cols - 13, y)] = "door"
    else:
        far = max((r for r in rooms if r["kind"] == "room"), key=lambda r: (path_len(t, start, _center(r["box"]), cols, rows) or 0, r["box"][2]))
        x0, y0, x1, y1 = far["box"]
        cx, cy = _center(far["box"])
        box = (max(2, min(x0, cx - 5)), max(2, min(y0, cy - 4)), min(cols - 3, max(x1, cx + 5)), min(rows - 3, max(y1, cy + 4)))
        rooms.remove(far)
        _fill(t, *box, floor)
    x0, y0, x1, y1 = box
    for px, py in ((x0 + 2, y0 + 2), (x1 - 2, y0 + 2), (x0 + 2, y1 - 2), (x1 - 2, y1 - 2)):
        if x1 - x0 >= 7 and y1 - y0 >= 6:
            t[_k(px, py)] = "wall"  # pillars to hide behind
    far_right = x1 if theme == "prison" or x0 > cols // 2 else x0
    side = -1 if far_right == x1 else 1
    t[_k(far_right + side, (y0 + y1) // 2)] = "table" if theme != "cave" else "rubble"  # the throne, the desk
    exit_xy = [far_right, (y0 + y1) // 2]
    t[_k(*exit_xy)] = "stairs"
    if theme == "dungeon":
        _doors(t, box, floor)
    name = rnd.choice(BOSS_NAMES[theme])
    rooms.append({"name": name, "kind": "boss", "box": list(box)})
    return exit_xy


def generate(theme="dungeon", seed=None, level=1):
    if theme not in THEMES:
        raise ValueError("Unknown theme")
    seed = int(seed if seed is not None else random.SystemRandom().randrange(1, 10 ** 9))
    for attempt in range(20):  # a layout where the stairs can't be reached is thrown away
        rnd = random.Random(seed + attempt * 7919)
        cols, rows = (44, 26) if theme == "prison" else (40, 28)
        t, rooms, floor = LAYOUTS[theme](rnd, cols, rows, level)
        first = rooms[0]
        first.update(kind="start", name=first["name"] if theme != "dungeon" else "Entrance")
        start = list(_center(first["box"]))
        exit_xy = _boss_room(t, rooms, theme, rnd, cols, rows, floor, start)
        t = _floor_back(t, rooms, floor, cols, rows)
        if path_len(t, start, exit_xy, cols, rows) is not None:
            return {"name": f"{THEMES[theme]['name']} — level {level}", "theme": theme, "seed": seed, "level": level,
                    "cols": cols, "rows": rows, "bg_color": THEMES[theme]["bg"], "terrain": t,
                    "rooms": rooms, "start": start, "exit": exit_xy}
    raise RuntimeError("Couldn't make a map that joins up")


def _floor_back(t, rooms, floor, cols, rows):
    """Paint every open square with the floor (the rest of the map is solid rock)."""
    out = {}
    for y in range(rows):
        for x in range(cols):
            out[_k(x, y)] = t.get(_k(x, y), floor)
    return out


def room_at(rooms, x, y):
    for r in rooms:
        x0, y0, x1, y1 = r["box"]
        if x0 <= x <= x1 and y0 <= y <= y1:
            return r
    return None
