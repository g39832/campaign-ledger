"""The missile silo: four levels going DOWN, built round one great launch shaft.

Levels 1-3: a ring corridor round the central shaft (the same missile stands in it on every level,
seen from a catwalk round the rim), rooms off the ring, and the freight lift down in the room on
the far right. Level 4 is the launch bay: three missiles in their tubes, a launch-abort panel under
each, the giant robot in the middle, and Steven Voss on his gantry by his escape lift (app/silo.py
runs the choice: take the missiles down and let Steven go, or go after him and let them fly).

All squares are new kinds of block (app/maps.py TERRAIN, drawn in mapview.js drawSilo), so the
silo doesn't look like the lab: poured concrete, hazard paint, mesh catwalks, the open shaft,
fuel tanks, pipes, consoles, bunks, weapon racks, crates, a reactor, cables and coolant spills.
"""
import random

SILO_LEVELS = 4

# walkable
FLOOR = "concrete"
# what the generator treats as solid (dungeon.SOLID gets these too)
SILO_SOLID = {"concretewall", "beacon", "shaft", "missile", "fueltank", "pipes", "reactor", "console", "bunk", "rack", "crate"}

ROOM_NAMES = ["Barracks", "Mess hall", "Armory", "Fuel store", "Generator hall", "Comms room", "Coolant pumps",
              "Warhead workshop", "Guidance lab", "Security checkpoint", "Drone hangar", "Storage bay",
              "Decontamination", "Blast shelter"]
SHAFT_NAMES = {1: "Shaft rim — the nose cone", 2: "Shaft rim — the fuel stage", 3: "Shaft rim — the engines"}

# Rooms that can open off the ring: (box, door, the square joining the door to the ring or None)
SLOTS = [
    ((2, 2, 7, 7), (8, 6), (9, 6)),
    ((2, 20, 7, 25), (8, 21), (9, 21)),
    ((10, 1, 15, 4), (12, 5), None),
    ((17, 1, 23, 4), (20, 5), None),
    ((25, 1, 30, 4), (27, 5), None),
    ((10, 23, 15, 26), (12, 22), None),
    ((17, 23, 23, 26), (20, 22), None),
    ((25, 23, 30, 26), (27, 22), None),
    ((33, 2, 38, 7), (32, 6), (31, 6)),
    ((33, 20, 38, 25), (32, 21), (31, 21)),
]
START_BOX = (2, 10, 7, 17)
LIFT_BOX = (33, 10, 38, 17)
HUB = (13, 9, 27, 18)  # inside the shaft hall's walls
SHAFT_C = (20, 13.5)


def _k(x, y):
    return f"{x},{y}"


def _fill(t, x0, y0, x1, y1, kind):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            t[_k(x, y)] = kind


def _ring(t, x0, y0, x1, y1, width, kind):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            if x < x0 + width or x > x1 - width or y < y0 + width or y > y1 - width:
                t[_k(x, y)] = kind


def _free(t, x, y):
    """Open concrete with no door next to it (so furniture never walls a door in)."""
    return t.get(_k(x, y)) in (FLOOR, "hazard") and not any(
        t.get(_k(x + dx, y + dy)) in ("silodoor", "lift") for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _put(t, spots, kind):
    for x, y in spots:
        if _free(t, x, y):
            t[_k(x, y)] = kind


def _dress(t, name, box, rnd):
    """Each kind of room gets its own blocks."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if name == "Barracks":
        _put(t, [(x, y) for x in range(x0, x1 + 1, 2) for y in (y0, y1)], "bunk")
    elif name == "Mess hall":
        _put(t, [(x, cy) for x in range(x0 + 1, x1)], "table")
    elif name == "Armory":
        _put(t, [(x, y0) for x in range(x0, x1 + 1)], "rack")
        _put(t, [(cx, cy + 1)], "crate")
    elif name == "Fuel store":
        _put(t, [(x0, y0), (x1, y0), (x0, y1), (x1, y1)], "fueltank")
        _put(t, [(cx, cy), (cx + 1, cy)], "hazard")
    elif name == "Generator hall":
        _put(t, [(cx, cy), (cx + 1, cy)], "reactor")
        _put(t, [(x, cy + 1) for x in range(x0, x1 + 1)] + [(x0, y) for y in range(y0, y1 + 1)], "cable")
    elif name == "Comms room":
        _put(t, [(x, y0) for x in range(x0, x1 + 1, 2)], "console")
        _put(t, [(cx, cy + 1)], "cable")
    elif name == "Coolant pumps":
        _put(t, [(x, y0) for x in range(x0, x1 + 1)], "pipes")
        _put(t, [(cx - 1, cy + 1), (cx, cy + 1), (cx, cy)], "coolant")
    elif name == "Warhead workshop":
        _put(t, [(cx, cy), (cx + 1, cy)], "crate")
        _put(t, [(x, y1) for x in range(x0, x1 + 1)], "hazard")
    elif name == "Guidance lab":
        _put(t, [(x0, y0), (x0 + 1, y0), (x1, y0)], "console")
        _put(t, [(cx, cy + 1)], "crate")
    elif name == "Security checkpoint":
        _put(t, [(cx - 1, cy), (cx + 1, cy)], "crate")
        _put(t, [(x, y1) for x in range(x0, x1 + 1)], "hazard")
    elif name == "Drone hangar":
        _put(t, [(cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)], "pad")
        _put(t, [(x0, y0), (x1, y0)], "rack")
    elif name == "Storage bay":
        for _ in range(4):
            _put(t, [(rnd.randint(x0, x1), rnd.randint(y0, y1))], "crate")
    elif name == "Decontamination":
        _put(t, [(x, y) for x in range(x0, x1 + 1) for y in (y0, y1)], "hazard")
        _put(t, [(cx, cy)], "coolant")
    elif name == "Blast shelter":
        _put(t, [(x0, y0), (x0 + 2, y0)], "bunk")
        _put(t, [(x1, y1), (x1 - 1, y1)], "crate")


def _walls_dress(t, cols, rows):
    """Amber beacons and pipe runs in the concrete walls that face a walkway, now and then."""
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            if t.get(_k(x, y)) != "concretewall":
                continue
            if any(t.get(_k(x + dx, y + dy)) in (FLOOR, "hazard", "catwalk", "cable", "coolant")
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                if (x * 7 + y * 3) % 9 == 0:
                    t[_k(x, y)] = "beacon"
                elif (x * 5 + y * 11) % 7 == 0:
                    t[_k(x, y)] = "pipes"


def _shaft_hall(t, rnd, level):
    """The launch shaft in the middle: open drop, the missile standing in it, a catwalk round the rim,
    hazard paint at the edge and spokes out to the hall's four doors (and on some levels a gantry arm
    out to the missile)."""
    x0, y0, x1, y1 = HUB
    cx, cy = SHAFT_C
    _ring(t, x0 - 1, y0 - 1, x1 + 1, y1 + 1, 1, "concretewall")
    _fill(t, x0, y0, x1, y1, FLOOR)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            e = ((x - cx) / 5.6) ** 2 + ((y - cy) / 4.0) ** 2
            if e <= 1:
                t[_k(x, y)] = "shaft"
            elif e <= 1.75:
                t[_k(x, y)] = "catwalk"
            elif e <= 2.4:
                t[_k(x, y)] = "hazard"
    _fill(t, 19, 12, 21, 14, "missile")
    doors = [(20, y0 - 1), (20, y1 + 1), (x0 - 1, 13), (x1 + 1, 14)]
    for dx, dy in doors:
        t[_k(dx, dy)] = "silodoor"
    for y in range(y0, 12):  # spokes from the doors to the catwalk
        if t[_k(20, y)] not in ("catwalk", "shaft"):
            t[_k(20, y)] = "catwalk"
    for y in range(y1, 14, -1):
        if t[_k(20, y)] not in ("catwalk", "shaft"):
            t[_k(20, y)] = "catwalk"
    for x in range(x0, 19):
        if t[_k(x, 13)] not in ("catwalk", "shaft"):
            t[_k(x, 13)] = "catwalk"
    for x in range(x1, 21, -1):
        if t[_k(x, 14)] not in ("catwalk", "shaft"):
            t[_k(x, 14)] = "catwalk"
    if level >= 2:  # a service gantry out over the drop to the missile
        side = rnd.choice((-1, 1))
        y = 13
        x = 18 if side < 0 else 22
        while t.get(_k(x, y)) == "shaft":
            t[_k(x, y)] = "catwalk"
            x += side


def _ring_level(rnd, cols, rows, level):
    t = {}
    _fill(t, 0, 0, cols - 1, rows - 1, "concretewall")
    _ring(t, 10, 6, 30, 21, 2, FLOOR)  # the ring corridor
    _shaft_hall(t, rnd, level)
    rooms = []
    _fill(t, *START_BOX, FLOOR)
    for y in (13, 14):
        t[_k(8, y)] = "silodoor"
        t[_k(9, y)] = FLOOR
    rooms.append({"name": "Surface hatch" if level == 1 else "Freight lift (arrival)", "kind": "start", "box": list(START_BOX)})
    if level == 1:
        _put(t, [(3, 11), (3, 16)], "crate")
    n = {1: 6, 2: 7, 3: 8}.get(level, 7)
    slots = rnd.sample(SLOTS, n)
    names = rnd.sample(ROOM_NAMES, n)
    for (box, door, link), name in zip(slots, names):
        _fill(t, *box, FLOOR)
        t[_k(*door)] = "silodoor"
        if link:
            t[_k(*link)] = FLOOR
        rooms.append({"name": name, "kind": "room", "box": list(box)})
    rooms.append({"name": SHAFT_NAMES.get(level, "Shaft rim"), "kind": "room", "box": list(HUB)})
    _fill(t, *LIFT_BOX, FLOOR)
    for y in (13, 14):
        t[_k(32, y)] = "silodoor"
        t[_k(31, y)] = FLOOR
    exit_xy = [37, 13]
    rooms.append({"name": "Freight lift", "kind": "boss", "box": list(LIFT_BOX)})
    for r in rooms:
        if r["kind"] == "room" and r["box"] != list(HUB):
            _dress(t, r["name"], r["box"], rnd)
    lx0, ly0, lx1, ly1 = LIFT_BOX  # the lift room: hazard paint round the lift, a control console
    _fill(t, 36, 12, 38, 15, "hazard")
    t[_k(*exit_xy)] = "lift"
    t[_k(38, 10)] = "console"
    t[_k(33, 10)] = t[_k(33, 17)] = "crate"
    _walls_dress(t, cols, rows)
    return t, rooms, list(START_BOX[:2]), exit_xy


# ---- level 4: the launch bay ----------------------------------------------------------------------
TUBES = [(19, 6), (26, 6), (33, 6)]  # missile centres
BAY = (14, 2, 37, 25)
CHECKPOINT = (8, 8, 12, 19)
GANTRY = (34, 17, 37, 24)  # Steven's platform, past a gap in the floor
STEVEN_AT = (36, 21)
ESCAPE_AT = (37, 21)  # his escape lift
ROBOT_AT = (23, 14)  # the robot's corner square (it's 3 squares across)


def abort_spots():
    """Where the three launch-abort panels go: just under each tube."""
    return [(x, 10) for x, _ in TUBES]


def _launch_bay(rnd, cols, rows):
    t = {}
    _fill(t, 0, 0, cols - 1, rows - 1, "concretewall")
    start = (2, 11, 6, 16)
    _fill(t, *start, FLOOR)
    _fill(t, *CHECKPOINT, FLOOR)
    for y in (13, 14):
        t[_k(7, y)] = "silodoor"
    _put(t, [(10, 11), (10, 16), (9, 13)], "crate")
    _fill(t, CHECKPOINT[0], CHECKPOINT[3], CHECKPOINT[2], CHECKPOINT[3], "hazard")
    _fill(t, *BAY, FLOOR)
    for y in (10, 11, 16, 17):
        t[_k(13, y)] = "silodoor"
    # the three tubes: a missile in the middle, the open drop round it, hazard paint round that
    for cx, cy in TUBES:
        for x in range(cx - 3, cx + 4):
            for y in range(cy - 3, cy + 4):
                d = max(abs(x - cx), abs(y - cy))
                if d <= 1:
                    t[_k(x, y)] = "missile"
                elif d == 2 and not (abs(x - cx) == 2 and abs(y - cy) == 2):
                    t[_k(x, y)] = "shaft"
                elif d == 2:
                    t[_k(x, y)] = "pipes"  # the tube's clamps at the corners
                elif BAY[1] <= y:
                    t[_k(x, y)] = "hazard"
        ax, ay = cx, 10
        t[_k(ax - 1, ay)] = t[_k(ax + 1, ay)] = "console"  # the abort panel sits between two consoles
    # the gap in front of Steven's gantry, with one narrow bridge across
    _fill(t, 32, 15, 33, 25, "shaft")
    _fill(t, 34, 15, 37, 16, "shaft")
    t[_k(32, 20)] = t[_k(33, 20)] = "catwalk"
    _fill(t, *GANTRY, "catwalk")
    t[_k(*ESCAPE_AT)] = "escape"
    t[_k(37, 17)] = "console"
    # cover and clutter across the floor
    _put(t, [(16, 13), (16, 14), (21, 20), (22, 20), (28, 13), (17, 22), (27, 22), (28, 22)], "crate")
    _put(t, [(15, 24), (30, 24)], "fueltank")
    _put(t, [(x, 18) for x in range(16, 21)] + [(26, y) for y in range(17, 25)], "cable")
    _put(t, [(19, 16), (20, 16), (29, 18), (29, 19)], "coolant")
    _fill(t, 14, 25, 31, 25, "hazard")
    for x in range(15, 32, 4):
        if _free(t, x, 2):
            t[_k(x, 2)] = "rack"
    rooms = [{"name": "Freight lift (arrival)", "kind": "start", "box": list(start)},
             {"name": "Security checkpoint", "kind": "room", "box": list(CHECKPOINT)},
             {"name": "Steven's gantry", "kind": "room", "box": list(GANTRY)},
             {"name": "The Launch Bay", "kind": "boss", "box": list(BAY)}]
    _walls_dress(t, cols, rows)
    return t, rooms, [4, 13], None


def generate(seed, level, path_len):
    """{name, cols, rows, terrain, rooms, start, exit} for dungeon.generate."""
    level = max(1, min(int(level), SILO_LEVELS))
    cols, rows = 40, 28
    for attempt in range(20):
        rnd = random.Random(seed + attempt * 7919)
        if level >= SILO_LEVELS:
            t, rooms, start, exit_xy = _launch_bay(rnd, cols, rows)
            goals = abort_spots() + [(STEVEN_AT[0], STEVEN_AT[1] - 1)]
        else:
            t, rooms, start, exit_xy = _ring_level(rnd, cols, rows, level)
            start = [4, 13]
            goals = [tuple(exit_xy)]
        if all(path_len(t, start, g, cols, rows) is not None for g in goals):
            name = f"Missile silo — level {level}" + (" (launch bay)" if level >= SILO_LEVELS else "")
            return {"name": name, "level": level, "cols": cols, "rows": rows, "terrain": t, "rooms": rooms,
                    "start": start, "exit": exit_xy}
    raise RuntimeError("Couldn't make a silo level that joins up")
