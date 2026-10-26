"""Ready-made battle maps, painted with terrain so they work without an image.

Each preset is a function of (cols, rows) that returns the terrain dict
{"x,y": kind} for that size. Layouts are drawn from a fixed random seed, so the
same preset always looks the same.
"""
import random

PRESETS = {}


def preset(key, name, description, cols, rows, bg):
    def wrap(fn):
        PRESETS[key] = {"key": key, "name": name, "description": description, "cols": cols, "rows": rows,
                        "bg_color": bg, "build": fn}
        return fn
    return wrap


def _rect(t, x0, y0, x1, y1, kind):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            t[f"{x},{y}"] = kind


def _border(t, x0, y0, x1, y1, kind):
    for x in range(x0, x1 + 1):
        t[f"{x},{y0}"] = kind
        t[f"{x},{y1}"] = kind
    for y in range(y0, y1 + 1):
        t[f"{x0},{y}"] = kind
        t[f"{x1},{y}"] = kind


def _clear(t, x, y):
    t.pop(f"{x},{y}", None)


@preset("tavern", "Tavern common room", "A bar, tables, a fireplace and two doors. Good for brawls and ambushes.", 24, 16, "#b08a5a")
def _tavern(cols, rows):
    t = {}
    _rect(t, 0, 0, cols - 1, rows - 1, "wood")
    _border(t, 0, 0, cols - 1, rows - 1, "wall")
    t[f"{cols // 2},{rows - 1}"] = "door"
    t[f"{cols - 1},3"] = "door"
    _rect(t, 2, 2, 9, 2, "table")          # the bar
    _rect(t, 9, 2, 9, 4, "table")
    _rect(t, cols - 4, rows - 4, cols - 2, rows - 2, "lava")  # fireplace
    _rect(t, cols - 5, rows - 5, cols - 2, rows - 5, "stone")
    _rect(t, cols - 5, rows - 4, cols - 5, rows - 2, "stone")
    for (x, y) in [(5, 7), (5, 11), (10, 8), (14, 5), (15, 11), (19, 7)]:
        _rect(t, x, y, x + 1, y, "table")
    _rect(t, 1, rows - 3, 3, rows - 2, "rubble")  # barrels and crates
    return t


@preset("cave", "Winding cave", "Twisting tunnels with a pool, loose rock and tight spots.", 30, 20, "#8c7b66")
def _cave(cols, rows):
    rnd = random.Random(7)
    solid = [[rnd.random() < 0.45 for _ in range(cols)] for _ in range(rows)]
    for _ in range(4):  # smooth the noise into cave walls
        nxt = []
        for y in range(rows):
            row = []
            for x in range(cols):
                n = sum(1 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx or dy)
                        and (not (0 <= x + dx < cols and 0 <= y + dy < rows) or solid[y + dy][x + dx]))
                row.append(n >= 5 or (n >= 4 and solid[y][x]))
            nxt.append(row)
        solid = nxt
    mid = rows // 2
    for x in range(cols):  # make sure one path runs end to end
        for y in (mid - 1, mid, mid + 1):
            solid[y][x] = False
    t = {}
    for y in range(rows):
        for x in range(cols):
            if solid[y][x] or x in (0, cols - 1) or y in (0, rows - 1):
                t[f"{x},{y}"] = "wall"
    for x in range(1, cols - 1):
        _clear(t, x, mid)
    _rect(t, cols - 9, 3, cols - 6, 5, "water")
    for (x, y) in [(6, mid - 1), (7, mid + 1), (15, mid), (16, mid - 1), (22, mid + 1)]:
        t[f"{x},{y}"] = "rubble"
    return t


@preset("forest", "Forest road", "A dirt road through the woods, with thick brush on both sides.", 30, 20, "#6f8f4e")
def _forest(cols, rows):
    rnd = random.Random(11)
    t = {}
    road = rows // 2
    for x in range(cols):
        y0 = road + (1 if (x // 6) % 2 else 0)
        _rect(t, x, y0 - 1, x, y0 + 1, "sand")
    for _ in range(int(cols * rows * 0.12)):
        x, y = rnd.randrange(cols), rnd.randrange(rows)
        if abs(y - road) > 2:
            t[f"{x},{y}"] = "tree" if rnd.random() < 0.55 else "foliage"
    for (x, y) in [(8, road - 3), (9, road - 3), (20, road + 3), (21, road + 3)]:
        t[f"{x},{y}"] = "rubble"  # fallen logs and rocks to hide behind
    return t


@preset("dungeon", "Dungeon rooms", "Three rooms joined by corridors, with doors and a pit trap.", 30, 20, "#2b2622")
def _dungeon(cols, rows):
    t = {}
    _rect(t, 0, 0, cols - 1, rows - 1, "wall")
    rooms = [(2, 2, 9, 8), (13, 3, 20, 10), (6, 12, 16, 17), (22, 12, 27, 17)]
    for (x0, y0, x1, y1) in rooms:
        _rect(t, x0, y0, x1, y1, "stone")
    for (x0, y0, x1, y1) in [(10, 5, 12, 5), (16, 11, 16, 11), (9, 9, 9, 11), (17, 14, 21, 14), (21, 8, 24, 8), (24, 9, 24, 11)]:
        _rect(t, x0, y0, x1, y1, "stone")
    for (x, y) in [(10, 5), (16, 11), (9, 11), (21, 14)]:
        t[f"{x},{y}"] = "door"
    _rect(t, 15, 6, 16, 7, "pit")
    _rect(t, 8, 14, 9, 15, "rubble")
    _rect(t, 25, 14, 25, 15, "table")  # an altar
    return t


@preset("bridge", "River crossing", "A wooden bridge over a fast river, trees on both banks.", 30, 20, "#6f8f4e")
def _bridge(cols, rows):
    rnd = random.Random(5)
    t = {}
    for y in range(rows):
        cx = cols // 2 + (1 if (y // 5) % 2 else 0)
        _rect(t, cx - 2, y, cx + 2, y, "water")
    _rect(t, cols // 2 - 3, rows // 2 - 1, cols // 2 + 3, rows // 2 + 1, "wood")
    for _ in range(40):
        x, y = rnd.randrange(cols), rnd.randrange(rows)
        if abs(x - cols // 2) > 4 and abs(y - rows // 2) > 1:
            t[f"{x},{y}"] = "tree" if rnd.random() < 0.6 else "foliage"
    for x in range(cols):
        if abs(x - cols // 2) > 3:
            t.setdefault(f"{x},{rows // 2}", "sand")
    return t


@preset("arena", "Arena", "A sand pit ringed by stone, with pillars for cover.", 24, 24, "#8a7f70")
def _arena(cols, rows):
    t = {}
    cx, cy, r = (cols - 1) / 2, (rows - 1) / 2, min(cols, rows) / 2 - 1
    for y in range(rows):
        for x in range(cols):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d <= r - 1:
                t[f"{x},{y}"] = "sand"
            elif d <= r:
                t[f"{x},{y}"] = "wall"
            else:
                t[f"{x},{y}"] = "stone"
    for (x, y) in [(7, 7), (16, 7), (7, 16), (16, 16)]:
        t[f"{x},{y}"] = "wall"
    t[f"{cols // 2},{rows - 2}"] = "door"
    t[f"{cols // 2},1"] = "door"
    return t


@preset("ship", "Ship deck", "A ship's deck on open water, with the mast and cargo.", 30, 18, "#3f6f8c")
def _ship(cols, rows):
    t = {}
    for y in range(3, rows - 3):
        _rect(t, 4, y, cols - 7, y, "wood")
    for i, y in enumerate(range(3, rows - 3)):  # pointed bow
        span = min(i, rows - 4 - y)
        _rect(t, cols - 6, y, min(cols - 2, cols - 6 + span), y, "wood")
    for y in range(3, rows - 3):
        t[f"4,{y}"] = "wall"
    _rect(t, 12, rows // 2, 12, rows // 2, "wall")       # mast
    _rect(t, 7, 4, 9, 5, "rubble")                      # cargo
    _rect(t, 18, rows - 6, 20, rows - 5, "rubble")
    t[f"6,{rows // 2}"] = "pit"                          # hatch
    return t


@preset("crypt", "Crypt", "Rows of tombs, pillars and a sealed door at the far end.", 24, 18, "#4a443d")
def _crypt(cols, rows):
    t = {}
    _rect(t, 0, 0, cols - 1, rows - 1, "stone")
    _border(t, 0, 0, cols - 1, rows - 1, "wall")
    for x in range(4, cols - 4, 4):
        _rect(t, x, 3, x + 1, 4, "table")
        _rect(t, x, rows - 5, x + 1, rows - 4, "table")
    for x in range(3, cols - 3, 4):
        t[f"{x},{rows // 2 - 2}"] = "wall"
        t[f"{x},{rows // 2 + 2}"] = "wall"
    t[f"0,{rows // 2}"] = "door"
    t[f"{cols - 1},{rows // 2}"] = "door"
    _rect(t, cols - 4, rows // 2 - 1, cols - 3, rows // 2 + 1, "rubble")
    return t


def build(key):
    p = PRESETS.get(key)
    if p is None:
        return None
    terrain = p["build"](p["cols"], p["rows"])
    terrain = {k: v for k, v in terrain.items()
               if 0 <= int(k.split(",")[0]) < p["cols"] and 0 <= int(k.split(",")[1]) < p["rows"]}
    return {"name": p["name"], "cols": p["cols"], "rows": p["rows"], "bg_color": p["bg_color"], "terrain": terrain}


def listing():
    return [{k: p[k] for k in ("key", "name", "description", "cols", "rows")} for p in PRESETS.values()]
