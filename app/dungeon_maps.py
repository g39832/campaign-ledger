"""Made-up maps in the campaign (app/dungeon.py makes the layout).

- The DM makes one (dungeon, cave or prison) on the Maps page. Fog is on: players see only the
  start room at first; the DM always sees the whole map, with a list of its rooms to show or hide.
- A hero walking into a room lights it up for the players (and the squares around them in a corridor).
- A hero stepping on the stairs (in the boss room) when no fight is running on the map: the next
  level is made, the party stands at its start, and it becomes the map everyone sees.
- The DM places monsters where they like with the map's monster panel, as on any map.
"""
import json
import uuid

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import get_db, new_uid, now_iso, tx
from .dungeon import THEMES, generate, room_at

bp = Blueprint("dungeon_maps", __name__, url_prefix="/api")
SIGHT = 2  # squares a hero in a corridor lights up around them


def _maps():
    from . import maps as M
    return M


def create(conn, cid, theme, level=1, seed=None, name=None, prev=None):
    """Make the map: terrain, fog on with the start room shown, and its dungeon record."""
    M = _maps()
    try:
        g = generate(theme, seed, level)
    except ValueError:
        raise F.ApiError("Pick dungeon, cave or prison")
    ts = now_iso()
    values = {"name": (name or g["name"])[:200], "cols": g["cols"], "rows": g["rows"], "bg_color": g["bg_color"], "fog_enabled": True}
    mid = F.insert(conn, "maps", F.MAP, values, {"uid": new_uid(), "campaign_id": cid, "revealed": "0" * (g["cols"] * g["rows"]),
                                                 "created_at": ts, "updated_at": ts})
    info = {k: g[k] for k in ("theme", "seed", "level", "rooms", "start", "exit")}
    info.update(prev=prev, next=None)
    conn.execute("UPDATE maps SET terrain = ?, dungeon = ? WHERE id = ?", (json.dumps(g["terrain"]), json.dumps(info), mid))
    start = next(r for r in g["rooms"] if r["kind"] == "start")
    _reveal_box(conn, mid, start["box"], True)
    M._bump(conn, mid)
    return mid


def _reveal_box(conn, mid, box, on, pad=1):
    """Show (or hide) a room to the players, with its walls."""
    M = _maps()
    m = M.map_dict(M._map_row(conn, mid))
    n = m["cols"] * m["rows"]
    bits = list((m["revealed"] + "0" * n)[:n])
    x0, y0, x1, y1 = box
    for y in range(max(0, y0 - pad), min(m["rows"], y1 + pad + 1)):
        for x in range(max(0, x0 - pad), min(m["cols"], x1 + pad + 1)):
            bits[y * m["cols"] + x] = "1" if on else "0"
    conn.execute("UPDATE maps SET revealed = ? WHERE id = ?", ("".join(bits), mid))


def _is_hero(conn, t):
    if t["character_id"]:
        return True
    if t["combatant_id"]:
        row = conn.execute("SELECT character_id FROM combatants WHERE id = ?", (t["combatant_id"],)).fetchone()
        return bool(row and row["character_id"])
    return False


def after_move(conn, m, t, x, y):
    """A token moved on a map. On a made-up map, a hero lights up the room they walk into (or the
    corridor around them), and stepping on the stairs takes the party down. Returns
    {map_id, name, level} when a new level was reached, else None."""
    d = m.get("dungeon") if isinstance(m, dict) else None
    if not d or not _is_hero(conn, t):
        return None
    x, y = int(round(x)), int(round(y))
    if m.get("fog_enabled"):
        r = room_at(d["rooms"], x, y)
        _reveal_box(conn, m["id"], r["box"] if r else [x - SIGHT + 1, y - SIGHT + 1, x + SIGHT - 1, y + SIGHT - 1], True)
    if [x, y] != list(d["exit"]):
        return None
    if m.get("encounter_id"):
        enc = conn.execute("SELECT status FROM encounters WHERE id = ?", (m["encounter_id"],)).fetchone()
        if enc and enc["status"] == "active":
            return {"blocked": True, "why": "The stairs won't open while the fight is still going"}
    return next_level(conn, m["id"])


def next_level(conn, map_id):
    """Down the stairs: the next level (made now, or the one made before), the party at its start,
    and it becomes the map the players see if this one was."""
    M = _maps()
    m = M.map_dict(M._map_row(conn, map_id))
    d = m["dungeon"]
    if not d:
        raise F.ApiError("That isn't a made-up map")
    nid = d.get("next")
    if not nid or not conn.execute("SELECT 1 FROM maps WHERE id = ?", (nid,)).fetchone():
        nid = create(conn, m["campaign_id"], d["theme"], level=int(d.get("level") or 1) + 1, prev=map_id)
        d["next"] = nid
        conn.execute("UPDATE maps SET dungeon = ? WHERE id = ?", (json.dumps(d), map_id))
    new = M.map_dict(M._map_row(conn, nid))
    # the heroes on this map go down together, around the start
    heroes = [t for t in conn.execute("SELECT * FROM map_tokens WHERE map_id = ?", (map_id,)).fetchall() if _is_hero(conn, t)]
    have = {r["character_id"] for r in conn.execute("SELECT character_id FROM map_tokens WHERE map_id = ? AND character_id IS NOT NULL", (nid,))}
    taken = {(int(round(r["x"])), int(round(r["y"]))) for r in conn.execute("SELECT x, y FROM map_tokens WHERE map_id = ?", (nid,))}
    sx, sy = new["dungeon"]["start"]
    chars = []
    for t in heroes:
        cid = t["character_id"]
        if not cid and t["combatant_id"]:
            cid = conn.execute("SELECT character_id FROM combatants WHERE id = ?", (t["combatant_id"],)).fetchone()["character_id"]
        if cid and cid not in have:
            chars.append(cid)
            have.add(cid)
    spots = M._open_spots(new, taken, sx, sy, len(chars))
    for cid, (x, y) in zip(chars, spots):
        conn.execute("INSERT INTO map_tokens (uid, map_id, kind, character_id, x, y, size, hidden, created_at, updated_at) "
                     "VALUES (?,?,'pc',?,?,?,1,0,?,?)", (uuid.uuid4().hex, nid, cid, x, y, now_iso(), now_iso()))
    live = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (m["campaign_id"],)).fetchone()["live_map_id"]
    if live == map_id:
        conn.execute("UPDATE campaigns SET live_map_id = ? WHERE id = ?", (nid, m["campaign_id"]))
    M._bump(conn, nid)
    M._bump(conn, map_id)
    return {"map_id": nid, "name": new["name"], "level": new["dungeon"]["level"], "live": live == map_id}


@bp.get("/dungeon-themes")
def api_themes():
    return jsonify({"themes": [{"key": k, "name": v["name"], "about": v["about"]} for k, v in THEMES.items()]})


@bp.post("/campaigns/<int:cid>/dungeons")
def api_make(cid):
    """Make a new made-up map. {theme: dungeon | cave | prison, name}"""
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (cid,)).fetchone() is None:
        raise F.NotFound("Campaign not found")
    with tx() as conn:
        mid = create(conn, cid, str(data.get("theme") or "dungeon"), name=str(data.get("name") or "").strip() or None)
    return jsonify(_maps().dm_state(mid)), 201


@bp.post("/maps/<int:map_id>/next-level")
def api_next(map_id):
    """The DM takes the party down the stairs now (or opens the next level to get it ready)."""
    with tx() as conn:
        went = next_level(conn, map_id)
    return jsonify({"next_level": went})


@bp.post("/maps/<int:map_id>/rooms/<int:index>/reveal")
def api_room(map_id, index):
    """Show a room to the players, or hide it again. {reveal: true | false}"""
    data = request.get_json(silent=True) or {}
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        rooms = (m.get("dungeon") or {}).get("rooms") or []
        if not 0 <= index < len(rooms):
            raise F.ApiError("That room isn't on this map")
        _reveal_box(conn, map_id, rooms[index]["box"], bool(data.get("reveal", True)))
        M._bump(conn, map_id)
    return jsonify(M.dm_state(map_id))
