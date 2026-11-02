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
    "dungeon": {"name": "Dungeon", "bg": "#2b2622", "about": "Stone rooms joined by corridors, with doors, traps and a boss's hall."},
    "cave": {"name": "Cave", "bg": "#3a332b", "about": "Winding caverns with pools and loose rock, ending in a great cavern."},
    "prison": {"name": "Prison", "bg": "#26231f", "about": "A gatehouse, cell blocks off long corridors, guard rooms, and the warden's office."},
    "jungle": {"name": "Jungle", "bg": "#2f4a25", "about": "Thick trees and bushes, muddy trails, a river, and an overgrown temple.",
               "structure": "stone", "exit_word": "the temple's stairs"},
    "swamp": {"name": "Swamp", "bg": "#33402c", "about": "Murky pools and reeds, rickety boardwalks, and a witch's hut.",
              "structure": "wood", "exit_word": "the trapdoor in the hut"},
    "desert": {"name": "Desert ruins", "bg": "#a08452", "about": "Open sand, rocky outcrops, broken walls, and a sunken tomb.",
               "structure": "stone", "exit_word": "the tomb's stairs"},
    "ice": {"name": "Ice cavern", "bg": "#33424a", "about": "Slippery ice, freezing pools and frozen pillars, up to a frozen throne."},
    "sewer": {"name": "Sewer", "bg": "#262a24", "about": "Sludge-filled tunnels, flooded chambers, and the great cistern."},
    "volcano": {"name": "Volcano", "bg": "#2a1a14", "about": "Hot stone caverns cut by rivers of lava, ending at a magma forge."},
}
# what you can't walk through (doors and rubble you can)
SOLID = {"wall", "pit", "water", "lava", "tree", "table", "rock"}
ROOM_NAMES = ["Guard post", "Storeroom", "Shrine", "Barracks", "Library", "Armory", "Crypt", "Kitchen", "Well room", "Trophy hall",
              "Torture chamber", "Old chapel", "Workshop", "Collapsed hall"]
BOSS_NAMES = {"dungeon": ["The Throne Room", "The Bone Hall", "The Black Altar"], "cave": ["The Great Cavern", "The Lair", "The Deep Pool"],
              "prison": ["The Warden's Office", "The Execution Hall", "The Deep Cells"],
              "jungle": ["The Overgrown Temple", "The Serpent Shrine", "The Idol's Court"], "swamp": ["The Witch's Hut", "The Rotting Hall", "The Hag's Lodge"],
              "desert": ["The Sunken Tomb", "The Sun Temple", "The Pharaoh's Vault"], "ice": ["The Frozen Throne", "The Glacier Heart", "The Frost Wyrm's Den"],
              "sewer": ["The Great Cistern", "The Rat King's Nest", "The Outflow"], "volcano": ["The Magma Forge", "The Fire Lord's Seat", "The Caldera"]}


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


def _corridor(t, a, b, floor, rnd, carve=("wall",)):
    """An L-shaped corridor between two points (keeps doors that are already there)."""
    (x0, y0), (x1, y1) = a, b
    if rnd.random() < 0.5:
        pts = [(x, y0) for x in range(min(x0, x1), max(x0, x1) + 1)] + [(x1, y) for y in range(min(y0, y1), max(y0, y1) + 1)]
    else:
        pts = [(x0, y) for y in range(min(y0, y1), max(y0, y1) + 1)] + [(x, y1) for x in range(min(x0, x1), max(x0, x1) + 1)]
    for x, y in pts:
        if t.get(_k(x, y)) in ("water", "lava") and t.get(_k(x, y)) in carve:
            t[_k(x, y)] = "wood"  # a bridge over the river (or the lava)
        elif t.get(_k(x, y)) in carve or t.get(_k(x, y)) is None:
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


# The open, natural places: noise smoothed into walls (rock, trees, water), clearings joined by
# a trail two squares wide, and the things that make each place itself.
WILDS = {
    "cave": {"floor": "sand", "wall": "wall", "density": 0.52, "trail": "sand", "extras": ["water", "rubble", "difficult", "rubble"],
             "start": "Cave mouth", "names": ["Dripping hollow", "Bat roost", "Glowing grotto", "Fungus garden", "Bone pile", "Echo chamber", "Crystal hall"]},
    "jungle": {"floor": "grass", "wall": "tree", "density": 0.5, "trail": "sand", "extras": ["foliage", "foliage", "difficult", "tree"], "river": "water",
               "start": "Jungle edge", "names": ["Vine tangle", "Fallen giant", "Orchid glade", "Monkey trees", "Old altar", "Snake hollow", "Waterfall pool"]},
    "swamp": {"floor": "grass", "wall": "water", "density": 0.47, "trail": "wood", "extras": ["difficult", "difficult", "foliage", "tree"],
              "start": "Boardwalk end", "names": ["Reed bed", "Sunken cart", "Will-o'-wisp pool", "Hanging moss", "Croc bank", "Drowned shrine", "Leech pond"]},
    "desert": {"floor": "sand", "wall": "rock", "density": 0.4, "trail": "sand", "extras": ["rubble", "difficult", "rubble", "wall"], "ruins": True,
               "start": "Oasis", "names": ["Broken colonnade", "Dune crest", "Bone field", "Old well", "Fallen statue", "Scorpion pit", "Market ruins"]},
    "ice": {"floor": "ice", "wall": "wall", "density": 0.5, "trail": "ice", "extras": ["water", "rubble", "ice", "wall"],
            "start": "Frozen gate", "names": ["Icicle hall", "Frozen falls", "Blue crevasse", "Mammoth bones", "Rime grotto", "Snow drift", "Glass lake"]},
    "volcano": {"floor": "stone", "wall": "wall", "density": 0.5, "trail": "stone", "extras": ["rubble", "lava", "difficult", "rubble"], "river": "lava",
                "start": "Ash slope", "names": ["Smoking vent", "Obsidian field", "Sulfur pool", "Cinder hall", "Collapsed tube", "Glass cave", "Ember garden"]},
}


def _wilds(rnd, cols, rows, level, kind="cave"):
    o = WILDS[kind]
    floor, wall = o["floor"], o["wall"]
    solid = [[rnd.random() < o["density"] for _ in range(cols)] for _ in range(rows)]
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
            edge = x in (0, cols - 1) or y in (0, rows - 1)
            t[_k(x, y)] = ("tree" if wall == "tree" else "wall") if edge else (wall if solid[y][x] else floor)
    # clearings: the start on the left, the last one on the right, a few in between
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
    if o.get("river"):  # a river (or lava) winding top to bottom through the middle (the trails cross it on bridges)
        x = rnd.randint(cols // 3, cols // 2)
        for y in range(1, rows - 1):
            x = max(cols // 4, min(cols - cols // 4, x + rnd.choice((-1, 0, 0, 1))))
            _fill(t, x, y, x + 1, y, o["river"])
    carve = (wall, "wall", "tree", "water", "rock", "lava")
    for a, b in zip(boxes, boxes[1:]):  # a trail two squares wide (a bridge or boardwalk over water and lava)
        _corridor(t, _center(a), _center(b), o["trail"] if o["trail"] != floor else floor, rnd, carve)
        _corridor(t, (_center(a)[0], _center(a)[1] + 1), (_center(b)[0], _center(b)[1] + 1), o["trail"] if o["trail"] != floor else floor, rnd, carve)
    for _ in range(int(cols * rows * 0.03)):
        x, y = rnd.randrange(1, cols - 1), rnd.randrange(1, rows - 1)
        if t[_k(x, y)] == floor:
            t[_k(x, y)] = rnd.choice(o["extras"])
    if o.get("ruins"):  # broken walls of old buildings in the sand
        for _ in range(4):
            x0, y0 = rnd.randint(9, cols - 18), rnd.randint(2, rows - 8)
            w, h = rnd.randint(4, 6), rnd.randint(3, 5)
            for x in range(x0, x0 + w):
                for y in (y0, y0 + h):
                    if rnd.random() < 0.6 and t.get(_k(x, y)) in (floor, "rubble"):
                        t[_k(x, y)] = "wall"
    names = [o["start"]] + rnd.sample(o["names"], len(boxes) - 2) + ["The far clearing"]
    rooms = [{"name": n, "kind": "room", "box": list(b)} for n, b in zip(names, boxes)]
    return t, rooms, floor


def _sewer(rnd, cols, rows, level):
    """Tunnels thick with sludge between chambers, some flooded, ending at the great cistern."""
    floor = "stone"
    t, boxes = _rooms_and_corridors(rnd, cols, rows, floor, 8)
    for k, v in list(t.items()):  # the tunnels run with sludge (slow going)
        x, y = map(int, k.split(","))
        if v == floor and not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes):
            t[k] = "difficult"
    names = ["Grate"] + rnd.sample(["Overflow chamber", "Rat warren", "Junction", "Collapsed pipe", "Smugglers' cache", "Pump room",
                                    "Fungus bloom", "Old cellar", "Sluice gate"], len(boxes) - 1)
    rooms = [{"name": n, "kind": "room", "box": list(b)} for n, b in zip(names, boxes)]
    for r in rooms[1:]:
        x0, y0, x1, y1 = r["box"]
        if rnd.random() < 0.6 and x1 - x0 >= 4:  # a flooded strip across the chamber, with a plank over it
            y = rnd.randint(y0 + 1, y1 - 1)
            _fill(t, x0, y, x1, y, "water")
            t[_k(rnd.randint(x0, x1), y)] = "wood"
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


LAYOUTS = {"dungeon": _dungeon, "prison": _prison, "sewer": _sewer,
           **{k: (lambda kind: lambda rnd, cols, rows, level: _wilds(rnd, cols, rows, level, kind))(k) for k in WILDS}}


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
        structure = THEMES[theme].get("structure")
        if structure:  # out in the wild the boss is in a building: walls round it, doors where the trails come in
            ring = [(x, box[1] - 1) for x in range(box[0] - 1, box[2] + 2)] + [(x, box[3] + 1) for x in range(box[0] - 1, box[2] + 2)] + \
                   [(box[0] - 1, y) for y in range(box[1], box[3] + 1)] + [(box[2] + 1, y) for y in range(box[1], box[3] + 1)]
            ways = [(x, y) for x, y in ring if walkable(t, x, y, cols, rows) and 0 < x < cols - 1 and 0 < y < rows - 1]
            for x, y in ring:
                if 0 <= x < cols and 0 <= y < rows:
                    t[_k(x, y)] = "wall"
            for x, y in (ways[::3] or [(box[0] - 1, (box[1] + box[3]) // 2)])[:4]:
                t[_k(x, y)] = "door"
            floor = structure
        _fill(t, *box, floor)
    x0, y0, x1, y1 = box
    for px, py in ((x0 + 2, y0 + 2), (x1 - 2, y0 + 2), (x0 + 2, y1 - 2), (x1 - 2, y1 - 2)):
        if x1 - x0 >= 7 and y1 - y0 >= 6:
            t[_k(px, py)] = "wall"  # pillars to hide behind
    far_right = x1 if theme == "prison" or x0 > cols // 2 else x0
    side = -1 if far_right == x1 else 1
    t[_k(far_right + side, (y0 + y1) // 2)] = "rubble" if theme in WILDS and not THEMES[theme].get("structure") else "table"  # the throne, the desk
    exit_xy = [far_right, (y0 + y1) // 2]
    t[_k(*exit_xy)] = "stairs"
    if theme in ("dungeon", "sewer"):
        _doors(t, box, floor)
    if theme == "sewer":  # the cistern: a pool in the middle
        _fill(t, (x0 + x1) // 2 - 1, (y0 + y1) // 2 - 1, (x0 + x1) // 2 + 1, (y0 + y1) // 2 + 1, "water")
    if theme == "volcano":
        for x in range(x0, x1 + 1):
            if t.get(_k(x, y1)) == floor and x % 3 == 0:
                t[_k(x, y1)] = "lava"
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
        first.update(kind="start", name="Entrance" if theme == "dungeon" else first["name"])
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


_THUMBS = None


def sample_thumbs():
    """One example of each kind of map, for the pictures on the Maps page (made once)."""
    global _THUMBS
    if _THUMBS is None:
        _THUMBS = []
        for k, v in THEMES.items():
            g = generate(k, 1234)
            _THUMBS.append({"key": k, "name": v["name"], "about": v["about"], "cols": g["cols"], "rows": g["rows"], "bg_color": g["bg_color"],
                            "terrain": g["terrain"]})
    return _THUMBS
