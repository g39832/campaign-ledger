"""What the heroes can see on a made-up map: line of sight, like the vision in Foundry or Roll20.

- Each hero sees VISION_FT (40 ft) in every direction from the edge of their token, but walls,
  steel bulkheads, sealed doors, trees, raised rock and big machines block the view. Open doorways,
  force fields, water, pits, tables and terminals don't (you can see over and through them).
- Squares a hero has seen stay on the players' map ("explored", the fog's memory), but only the
  squares someone can see right now are lit; the rest are drawn dimmed. Enemies show on the
  players' map only while a hero can see them.
- The view is worked out by walking the grid along the line from the viewer's centre to each square
  (every square the line passes through, so it never slips through a wall), squeezing between two
  walls that only touch at a corner is blocked, and a wall's near face is seen when it's in view.
"""
import math

VISION_FT = 40
OPAQUE = {"wall", "rock", "tree", "bulkhead", "sealed", "panel", "camera", "turret", "redlight", "machinery",
          "concretewall", "beacon", "pipes", "missile", "fueltank", "reactor"}  # the missile silo


def _ft_per_square(m):
    return int(m.get("scale_value") or 5) if (m.get("scale_unit") or "ft") == "ft" else 5


def _clear(opaque, x0, y0, x1, y1, target, own):
    """Nothing opaque between (x0, y0) and (x1, y1), except the target square itself."""
    cx, cy = math.floor(x0), math.floor(y0)
    dx, dy = x1 - x0, y1 - y0
    sx = 1 if dx > 0 else -1 if dx < 0 else 0
    sy = 1 if dy > 0 else -1 if dy < 0 else 0
    tdx = abs(1 / dx) if dx else math.inf
    tdy = abs(1 / dy) if dy else math.inf
    tmx = ((cx + 1 - x0) if dx > 0 else (x0 - cx)) * tdx if dx else math.inf
    tmy = ((cy + 1 - y0) if dy > 0 else (y0 - cy)) * tdy if dy else math.inf
    for _ in range(200):
        if (cx, cy) == target:
            return True
        if (cx, cy) not in own and opaque(cx, cy):
            return False
        if tmx < tmy - 1e-9:
            cx += sx
            tmx += tdx
        elif tmy < tmx - 1e-9:
            cy += sy
            tmy += tdy
        else:  # exactly through a corner: two walls touching there block it
            a, b = (cx + sx, cy), (cx, cy + sy)
            if opaque(*a) and opaque(*b) and target not in (a, b):
                return False
            cx += sx
            cy += sy
            tmx += tdx
            tmy += tdy
        if min(tmx, tmy) > 1 + 1e-9 and (cx, cy) != target:
            return False
    return False


def opaque_grid(terrain, cols, rows):
    """What blocks the view, as one flag per square (much quicker to look up than the terrain's names)."""
    g = bytearray(cols * rows)
    for k, v in terrain.items():
        if v in OPAQUE:
            c = k.find(",")
            a, b = int(k[:c]), int(k[c + 1:])
            if 0 <= a < cols and 0 <= b < rows:
                g[b * cols + a] = 1
    return g


def sight(terrain, cols, rows, x, y, size=1, radius_sq=8):
    """The squares a token at (x, y) can see: {(x, y)}."""
    x, y = int(round(x)), int(round(y))
    own = {(x + a, y + b) for a in range(size) for b in range(size)}
    grid = opaque_grid(terrain, cols, rows)

    def opaque(a, b):
        return not (0 <= a < cols and 0 <= b < rows) or grid[b * cols + a] == 1
    cx, cy = x + size / 2, y + size / 2
    reach = radius_sq + size / 2
    out = set(own)
    for ty in range(max(0, int(cy - reach - 1)), min(rows, int(cy + reach + 1) + 1)):
        for tx in range(max(0, int(cx - reach - 1)), min(cols, int(cx + reach + 1) + 1)):
            if (tx, ty) in out:
                continue
            nx, ny = min(max(cx, tx), tx + 1), min(max(cy, ty), ty + 1)  # the square's nearest point
            if math.hypot(nx - cx, ny - cy) >= reach - 1e-6:  # (a square 45 ft away starts right at 40 ft: not in view)
                continue
            # try the near edge (a wall's face), then the middle and corners (seeing part of a square counts)
            pts = [(min(max(cx, tx + 0.02), tx + 0.98), min(max(cy, ty + 0.02), ty + 0.98))]
            if opaque(tx, ty):  # a wall: any point along the faces turned towards the viewer
                fy = ty + 0.98 if cy > ty + 1 else ty + 0.02 if cy < ty else None
                fx = tx + 0.98 if cx > tx + 1 else tx + 0.02 if cx < tx else None
                if fy is not None:
                    pts += [(tx + f, fy) for f in (0.05, 0.5, 0.95)]
                if fx is not None:
                    pts += [(fx, ty + f) for f in (0.05, 0.5, 0.95)]
            else:
                pts += [(tx + 0.5, ty + 0.5), (tx + 0.1, ty + 0.1), (tx + 0.9, ty + 0.1), (tx + 0.1, ty + 0.9), (tx + 0.9, ty + 0.9)]
            if any(_clear(opaque, cx, cy, px, py, (tx, ty), own) for px, py in pts):
                out.add((tx, ty))
    return out


def radius_squares(m):
    ft = int(((m.get("dungeon") or {}).get("vision_ft")) or VISION_FT)
    return max(1, ft // _ft_per_square(m))


def has_vision(m):
    return bool(m.get("dungeon")) and bool(m.get("fog_enabled"))


_cache = {}


def party_sight(conn, m):
    """Every square some hero on this map can see right now (cached for this version of the map)."""
    key = (m["id"], m.get("rev"))
    if key in _cache:
        return _cache[key]
    seen = set()
    r = radius_squares(m)
    for t in conn.execute("SELECT t.x, t.y, t.size, t.character_id, t.combatant_id, cb.character_id AS cb_char, "
                          "COALESCE(ch.status, '') AS st FROM map_tokens t LEFT JOIN combatants cb ON cb.id = t.combatant_id "
                          "LEFT JOIN characters ch ON ch.id = COALESCE(t.character_id, cb.character_id) "
                          "WHERE t.map_id = ? AND t.hidden = 0", (m["id"],)):
        if not (t["character_id"] or t["cb_char"]) or t["st"] == "dead":
            continue
        seen |= sight(m["terrain"], m["cols"], m["rows"], t["x"], t["y"], t["size"], r)
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = seen
    return seen


def bitmap(m, cells):
    bits = ["0"] * (m["cols"] * m["rows"])
    for x, y in cells:
        if 0 <= x < m["cols"] and 0 <= y < m["rows"]:
            bits[y * m["cols"] + x] = "1"
    return "".join(bits)


def seen_along(m, x0, y0, x1, y1, size=1):
    """What a hero saw walking from one square to another (every square on the way)."""
    r = radius_squares(m)
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
    out = set()
    for i in range(steps + 1):
        px, py = x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps
        if m["terrain"].get(f"{int(round(px))},{int(round(py))}") in OPAQUE:
            continue  # (a free move straight through a wall: nobody stood in it)
        out |= sight(m["terrain"], m["cols"], m["rows"], x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, size, r)
    return out
