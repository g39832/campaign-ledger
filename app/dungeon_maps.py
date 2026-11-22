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


def _maps():
    from . import maps as M
    return M


PLAYTEST = "Playtest — "


def create(conn, cid, theme, level=1, seed=None, name=None, prev=None, prefix=""):
    """Make the map: terrain, fog on with the start room shown, and its dungeon record."""
    M = _maps()
    try:
        g = generate(theme, seed, level)
    except ValueError:
        raise F.ApiError("Pick a kind of map: dungeon, cave, prison, abandoned prison...")
    ts = now_iso()
    values = {"name": (prefix + (name or g["name"]))[:200], "cols": g["cols"], "rows": g["rows"], "bg_color": g["bg_color"], "fog_enabled": True}
    mid = F.insert(conn, "maps", F.MAP, values, {"uid": new_uid(), "campaign_id": cid, "revealed": "0" * (g["cols"] * g["rows"]),
                                                 "created_at": ts, "updated_at": ts})
    info = {k: g[k] for k in ("theme", "seed", "level", "rooms", "start", "exit")}
    info.update(prev=prev, next=None)
    conn.execute("UPDATE maps SET terrain = ?, dungeon = ? WHERE id = ?", (json.dumps(g["terrain"]), json.dumps(info), mid))
    start = next(r for r in g["rooms"] if r["kind"] == "start")
    _reveal_box(conn, mid, start["box"], True)
    M._bump(conn, mid)
    if theme == "futureprison":  # the abandoned prison comes with its enemies and chests
        from .prison import furnish
        furnish(conn, mid)
    elif theme == "lab":  # so does the laboratory (tougher each floor)
        from .lab import furnish as lab_furnish
        lab_furnish(conn, mid)
    elif theme == "silo":  # and the missile silo (tougher each level down; the launch bay at the bottom)
        from .silo import furnish as silo_furnish
        silo_furnish(conn, mid)
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


def _reveal_cells(conn, mid, cells):
    """Show these squares to the players (the fog's memory: once seen, they stay on the map)."""
    if not cells:
        return
    M = _maps()
    m = M.map_dict(M._map_row(conn, mid))
    n = m["cols"] * m["rows"]
    bits = list((m["revealed"] + "0" * n)[:n])
    for x, y in cells:
        if 0 <= x < m["cols"] and 0 <= y < m["rows"]:
            bits[y * m["cols"] + x] = "1"
    conn.execute("UPDATE maps SET revealed = ? WHERE id = ?", ("".join(bits), mid))


def look_around(conn, mid):
    """Every hero on the map looks around (after they're put somewhere): what they see is revealed."""
    from .vision import has_vision, radius_squares, sight
    M = _maps()
    m = M.map_dict(M._map_row(conn, mid))
    if not has_vision(m):
        return
    seen = set()
    for t in conn.execute("SELECT * FROM map_tokens WHERE map_id = ?", (mid,)).fetchall():
        if _is_hero(conn, t) and not t["hidden"]:
            seen |= sight(m["terrain"], m["cols"], m["rows"], t["x"], t["y"], t["size"], radius_squares(m))
    _reveal_cells(conn, mid, seen)


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
    r = room_at(d["rooms"], x, y)
    if m.get("fog_enabled"):
        if r:
            _reveal_box(conn, m["id"], r["box"], True)  # walking into a room lights it up
        # and what they see on the way, 40 ft round them, as far as the walls let them (app/vision.py)
        from .vision import seen_along
        _reveal_cells(conn, m["id"], seen_along(m, int(round(t["x"])), int(round(t["y"])), x, y, t["size"]))
    from .vision import has_vision
    if has_vision(m):
        sight_fight(conn, m)  # someone sees someone: a fight between them is about to start
    elif r:
        room_fight(conn, m, r, t)  # monsters in the room: a fight is about to start
    if not d.get("exit") or [x, y] != list(d["exit"]):  # (the lab's top floor has no way up)
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
    if not d.get("exit"):
        raise F.ApiError("This is the top floor — there's no way any further")
    nid = d.get("next")
    if not nid or not conn.execute("SELECT 1 FROM maps WHERE id = ?", (nid,)).fetchone():
        nid = create(conn, m["campaign_id"], d["theme"], level=int(d.get("level") or 1) + 1, prev=map_id,
                     prefix=PLAYTEST if m["name"].startswith(PLAYTEST) else "")  # a playtest copy's floors stay marked
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
        kind = (conn.execute("SELECT kind FROM characters WHERE id = ?", (cid,)).fetchone() or {"kind": "pc"})["kind"]
        conn.execute("INSERT INTO map_tokens (uid, map_id, kind, character_id, x, y, size, hidden, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,1,0,?,?)", (uuid.uuid4().hex, nid, "npc" if kind == "npc" else "pc", cid, x, y, now_iso(), now_iso()))
    look_around(conn, nid)
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


@bp.post("/maps/<int:map_id>/silo")
def api_silo(map_id):
    """The DM runs the launch bay's ending by hand. {action: aborted | caught | timeout | more | less | reset}"""
    from . import silo
    action = str((request.get_json(silent=True) or {}).get("action") or "")
    with tx() as conn:
        if action in silo.OUTCOMES:
            silo.decide(conn, map_id, action)
        elif action in ("more", "less"):
            silo.more_rounds(conn, map_id, 2 if action == "more" else -2)
        elif action == "reset":
            silo.reset(conn, map_id)
        else:
            raise F.ApiError("Pick what happens")
    return jsonify(_maps().dm_state(map_id))


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


def _party_ids(conn, cid):
    return [r["id"] for r in conn.execute("SELECT id FROM characters WHERE campaign_id = ? AND kind = 'pc' AND archived = 0 ORDER BY name", (cid,))]


@bp.post("/maps/<int:map_id>/party-to-start")
def api_party_to_start(map_id):
    """Every hero in the campaign stands at the start: the ones already on the map move there,
    the rest are added."""
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        d = m.get("dungeon")
        if not d:
            raise F.ApiError("That isn't a made-up map")
        sx, sy = d["start"]
        mine = {r["character_id"]: r["id"] for r in conn.execute(
            "SELECT id, character_id FROM map_tokens WHERE map_id = ? AND character_id IS NOT NULL", (map_id,))}
        party = _party_ids(conn, m["campaign_id"])
        others = {(int(round(r["x"])), int(round(r["y"]))) for r in conn.execute(
            "SELECT x, y, character_id FROM map_tokens WHERE map_id = ?", (map_id,)) if r["character_id"] not in party}
        spots = M._open_spots(m, others, sx, sy, len(party))
        for cid, (x, y) in zip(party, spots):
            if cid in mine:
                conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (x, y, now_iso(), mine[cid]))
            else:
                conn.execute("INSERT INTO map_tokens (uid, map_id, kind, character_id, x, y, size, hidden, created_at, updated_at) "
                             "VALUES (?,?,'pc',?,?,?,1,0,?,?)", (uuid.uuid4().hex, map_id, cid, x, y, now_iso(), now_iso()))
        start = next(r for r in d["rooms"] if r["kind"] == "start")
        _reveal_box(conn, map_id, start["box"], True)
        look_around(conn, map_id)
        M._bump(conn, map_id)
    return jsonify(M.dm_state(map_id))


@bp.post("/maps/<int:map_id>/reroll")
def api_reroll(map_id):
    """Don't like it? A brand new layout for this map (same kind, same level). The heroes go to the
    new start; monsters and markers placed on the old layout are taken off."""
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        d = m.get("dungeon")
        if not d:
            raise F.ApiError("That isn't a made-up map")
        g = generate(d["theme"], None, int(d.get("level") or 1))
        info = dict(d, **{k: g[k] for k in ("seed", "rooms", "start", "exit")})
        conn.execute("UPDATE maps SET terrain = ?, dungeon = ?, cols = ?, rows = ?, revealed = ? WHERE id = ?",
                     (json.dumps(g["terrain"]), json.dumps(info), g["cols"], g["rows"], "0" * (g["cols"] * g["rows"]), map_id))
        gone = [r["id"] for r in conn.execute("SELECT t.id, t.character_id, t.combatant_id FROM map_tokens t WHERE t.map_id = ?", (map_id,))
                if not _is_hero(conn, r)]
        for tid in gone:
            conn.execute("DELETE FROM map_tokens WHERE id = ?", (tid,))
        m = M.map_dict(M._map_row(conn, map_id))
        heroes = [r for r in conn.execute("SELECT * FROM map_tokens WHERE map_id = ?", (map_id,))]
        sx, sy = g["start"]
        for t, (x, y) in zip(heroes, M._open_spots(m, set(), sx, sy, len(heroes))):
            conn.execute("UPDATE map_tokens SET x = ?, y = ? WHERE id = ?", (x, y, t["id"]))
        start = next(r for r in g["rooms"] if r["kind"] == "start")
        _reveal_box(conn, map_id, start["box"], True)
        look_around(conn, map_id)
        M._bump(conn, map_id)
        if d["theme"] in ("futureprison", "lab", "silo"):  # new rooms: new enemies and chests
            from .lab import furnish as lab_furnish
            from .prison import clear, furnish
            from .silo import furnish as silo_furnish
            clear(conn, map_id)
            if d["theme"] == "silo":
                conn.execute("DELETE FROM map_tokens WHERE map_id = ? AND label = 'Steven Voss'", (map_id,))
            {"lab": lab_furnish, "silo": silo_furnish}.get(d["theme"], furnish)(conn, map_id)
    return jsonify(M.dm_state(map_id))



# ---- a fight when the party walks into a room with monsters -----------------------------------

def _fight_running(conn, m):
    if not m.get("encounter_id"):
        return False
    row = conn.execute("SELECT status FROM encounters WHERE id = ?", (m["encounter_id"],)).fetchone()
    return bool(row and row["status"] == "active")


def _hero_char(conn, tok):
    return tok["character_id"] or conn.execute("SELECT character_id FROM combatants WHERE id = ?", (tok["combatant_id"],)).fetchone()["character_id"]


def _start_fight(conn, m, foes, hero_toks, place, by, what, picked=False):
    """Set up a fight on this map: these foes (rows with tok, cb, name) and these heroes' tokens.
    The foes come out of hiding; the DM gets one button to roll initiative and start, and the
    players wait until then. picked: only these heroes are in it (the DM adds the others later)."""
    d = m.get("dungeon") or {}
    from .combat import Ctx
    ts = now_iso()
    eid = F.insert(conn, "encounters", F.ENCOUNTER, {"name": f"{place} ({m['name']})"[:200]},
                   {"uid": new_uid(), "campaign_id": m["campaign_id"], "created_at": ts, "updated_at": ts})
    ids = [f["cb"] for f in foes]
    conn.execute(f"UPDATE combatants SET encounter_id = ?, hidden = 0, init_roll = NULL WHERE id IN ({','.join('?' * len(ids))})", (eid, *ids))
    conn.execute(f"UPDATE map_tokens SET hidden = 0 WHERE id IN ({','.join('?' * len(foes))})", [f["tok"] for f in foes])
    ctx = Ctx(conn, eid)
    heroes = []
    for tok in hero_toks:
        cid = _hero_char(conn, tok)
        ch = conn.execute("SELECT * FROM characters WHERE id = ?", (cid,)).fetchone()
        if ch is None or ch["id"] in [h[0] for h in heroes]:
            continue
        add_hero(conn, ctx, ch, tok["id"])
        heroes.append((ch["id"], ch["name"]))
    names = [f["name"] for f in foes]
    ctx.log("system", f"{what} — {place}: {', '.join(names)}! Roll initiative"
            + (f" ({', '.join(h[1] for h in heroes)} in the fight; add the others when they get there)" if picked else ""))
    conn.execute("UPDATE maps SET encounter_id = ? WHERE id = ?", (eid, m["id"]))
    d["fight"] = {"eid": eid, "room": place, "by": by, "what": what, "foes": names, "at": ts, "heroes": [h[1] for h in heroes]}
    if picked:
        d["picked"] = eid  # the party isn't pulled in all at once: the DM adds them
    conn.execute("UPDATE maps SET dungeon = ? WHERE id = ?", (json.dumps(d), m["id"]))
    m["dungeon"], m["encounter_id"] = d, eid
    return d["fight"]


def add_hero(conn, ctx, ch, token_id=None):
    """A hero joins this fight (their token on the map points at them in it)."""
    from .combat import _next_sort
    from .rules import derived
    chd = F.decode_row(ch, F.CHARACTER)
    cur = conn.execute("INSERT INTO combatants (uid, encounter_id, character_id, kind, name, init_mod, init_roll, sort_order, max_hp, current_hp, ac, created_at) "
                       "VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?)",
                       (new_uid(), ctx.enc["id"], ch["id"], ch["kind"], ch["name"], derived(chd)["initiative"], _next_sort(ctx), ch["max_hp"], ch["current_hp"], ch["ac"], now_iso()))
    if token_id:
        conn.execute("UPDATE map_tokens SET combatant_id = ? WHERE id = ?", (cur.lastrowid, token_id))
    return cur.lastrowid


def _live_foes(conn, m):
    return conn.execute(
        "SELECT t.id AS tok, t.x, t.y, t.size, cb.id AS cb, cb.name, cb.statblock FROM map_tokens t JOIN combatants cb ON cb.id = t.combatant_id "
        "WHERE t.map_id = ? AND cb.kind = 'enemy' AND cb.status NOT IN ('dead', 'defeated', 'fled') AND cb.current_hp > 0",
        (m["id"],)).fetchall()


def room_fight(conn, m, room, t):
    """A hero stepped into a room where monsters stand: a fight with them (and the party on this map).
    (Maps without fog. On made-up maps with fog it's sight_fight: whoever sees whom.) Returns the fight's note, or None."""
    d = m.get("dungeon") or {}
    if d.get("fight") or _fight_running(conn, m):
        return None
    x0, y0, x1, y1 = room["box"]
    foes = [f for f in _live_foes(conn, m) if x0 <= int(round(f["x"])) <= x1 and y0 <= int(round(f["y"])) <= y1]
    if not foes:
        return None
    heroes = [tok for tok in conn.execute("SELECT * FROM map_tokens WHERE map_id = ?", (m["id"],)).fetchall() if _is_hero(conn, tok)]
    who = conn.execute("SELECT name FROM characters WHERE id = ?", (_hero_char(conn, t),)).fetchone()["name"]
    return _start_fight(conn, m, foes, heroes, room["name"], who, f"{who} walks into {room['name']}")


def enemy_sight_squares(statblock, m):
    """How far an enemy sees: 40 ft, or farther with darkvision, blindsight or truesight in its senses."""
    import re
    from .vision import VISION_FT, _ft_per_square
    try:
        senses = str((json.loads(statblock or "{}") if isinstance(statblock, str) else (statblock or {})).get("senses") or "")
    except ValueError:
        senses = ""
    ft = max([VISION_FT] + [int(n) for n in re.findall(r"(?:darkvision|blindsight|truesight|tremorsense)\s*(\d+)", senses, re.I)])
    return max(1, ft // _ft_per_square(m))


def sight_fight(conn, m):
    """On a made-up map with fog: a hero who can see an enemy (it stands on a square lit by their view)
    starts a fight between them. Enemies out of the heroes' view never start one, even if they can see
    the heroes. The enemies in the same room come too (they hear it). Only the heroes who see
    them (or are seen) are in it; the DM adds the rest of the party when they get there. Returns the
    fight's note, or None."""
    from .vision import has_vision, radius_squares, sight
    d = m.get("dungeon") or {}
    if not has_vision(m) or d.get("fight") or _fight_running(conn, m):
        return None
    M = _maps()
    m = M.map_dict(M._map_row(conn, m["id"]))  # (the terrain and positions as they are now)
    heroes = [t for t in conn.execute("SELECT * FROM map_tokens WHERE map_id = ? AND hidden = 0", (m["id"],)).fetchall() if _is_hero(conn, t)]
    heroes = [t for t in heroes if (conn.execute("SELECT status FROM characters WHERE id = ?", (_hero_char(conn, t),)).fetchone() or {"status": "ok"})["status"]
              not in ("dead", "unconscious")]
    foes = _live_foes(conn, m)
    if not heroes or not foes:
        return None
    r = radius_squares(m)
    cells = lambda t: {(int(round(t["x"])) + a, int(round(t["y"])) + b) for a in range(t["size"]) for b in range(t["size"])}
    reach = {f["tok"]: enemy_sight_squares(f["statblock"], m) for f in foes}
    close = lambda h, f: max(abs(h["x"] - f["x"]), abs(h["y"] - f["y"])) <= max(reach[f["tok"]], r) + 2
    # only heroes with an enemy anywhere near need to look (the rest can't see or be seen by anyone)
    heroes = [h for h in heroes if any(close(h, f) for f in foes)]
    if not heroes:
        return None
    hero_sees = {t["id"]: sight(m["terrain"], m["cols"], m["rows"], t["x"], t["y"], t["size"], r) for t in heroes}
    met = {}  # foe token -> set of hero token ids
    for f in foes:
        near = [h for h in heroes if close(h, f)]
        if not near:
            continue
        # only what the heroes can see right now (the lit squares) starts a fight: an enemy that sees
        # them from the dark (darkvision) waits until it's in their view (2026-11-15, Grayson)
        who = {h["id"] for h in near if cells(f) & hero_sees[h["id"]]}
        if who:
            met[f["tok"]] = who
    if not met:
        return None
    rooms = d.get("rooms") or []
    spotted = [f for f in foes if f["tok"] in met]
    their_rooms = [room_at(rooms, int(round(f["x"])), int(round(f["y"]))) for f in spotted]
    group = [f for f in foes if f["tok"] in met or any(rm and room_at([rm], int(round(f["x"])), int(round(f["y"]))) for rm in their_rooms)]
    in_fight = set().union(*met.values())
    hero_toks = [h for h in heroes if h["id"] in in_fight]
    names = [conn.execute("SELECT name FROM characters WHERE id = ?", (_hero_char(conn, h),)).fetchone()["name"] for h in hero_toks]
    place = next((rm["name"] for rm in their_rooms if rm), "Ambush")
    seen_first = any(cells(f) & hero_sees[h] for f in spotted for h in met[f["tok"]])
    who = (" and ".join(names) + (" spots " if seen_first else " is spotted by ") + ", ".join(f["name"] for f in spotted))
    return _start_fight(conn, m, group, hero_toks, place, names[0], who, picked=True)


@bp.post("/maps/<int:map_id>/fight-join")
def api_fight_join(map_id):
    """The DM brings another hero into the map's fight. {character_id}. In a running fight they roll
    initiative straight away and take their place in the order."""
    from .combat import Ctx, _resort, roll_missing_initiative
    data = request.get_json(silent=True) or {}
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        if not m.get("encounter_id"):
            raise F.ApiError("There's no fight on this map")
        try:
            cid = int(data.get("character_id"))
        except (TypeError, ValueError):
            raise F.ApiError("Who joins?")
        ch = conn.execute("SELECT * FROM characters WHERE id = ? AND campaign_id = ?", (cid, m["campaign_id"])).fetchone()
        if ch is None:
            raise F.NotFound("That character isn't in this campaign")
        ctx = Ctx(conn, m["encounter_id"])
        if ctx.enc["status"] == "ended":
            raise F.ApiError("That fight is over")
        if conn.execute("SELECT 1 FROM combatants WHERE encounter_id = ? AND character_id = ?", (ctx.enc["id"], cid)).fetchone():
            raise F.ApiError(f"{ch['name']} is already in the fight")
        tok = conn.execute("SELECT t.id FROM map_tokens t LEFT JOIN combatants cb ON cb.id = t.combatant_id "
                           "WHERE t.map_id = ? AND (t.character_id = ? OR cb.character_id = ?) LIMIT 1", (map_id, cid, cid)).fetchone()
        add_hero(conn, ctx, ch, tok["id"] if tok else None)
        rolled = []
        if ctx.enc["status"] == "active":
            rolled = roll_missing_initiative(ctx)
            if ctx.settings["auto_sort"]:
                _resort(ctx)
        ctx.log("roster", f"{ch['name']} joins the fight")
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["id"]))
        M._bump(conn, map_id)
    return jsonify(M.dm_state(map_id) | {"joined": ch["name"], "rolled": rolled})


@bp.post("/maps/<int:map_id>/room-fight")
def api_room_fight(map_id):
    """The DM answers a room fight: {action: "start"} rolls initiative for everyone who hasn't got one
    and starts round 1; {action: "wait"} lets the party move on (the fight stays ready on the Combat screen)."""
    from .combat import Ctx, roll_missing_initiative, start_fight
    data = request.get_json(silent=True) or {}
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        d = m.get("dungeon") or {}
        f = d.get("fight")
        if not f:
            raise F.ApiError("There's no fight waiting to start here")
        out = {"encounter_id": f["eid"]}
        if data.get("action") == "start":
            ctx = Ctx(conn, f["eid"])
            out["rolled"] = roll_missing_initiative(ctx)
            start_fight(ctx)
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), f["eid"]))
        d.pop("fight", None)
        conn.execute("UPDATE maps SET dungeon = ? WHERE id = ?", (json.dumps(d), map_id))
        M._bump(conn, map_id)
    return jsonify(M.dm_state(map_id) | {"room_fight": out})
