"""Chests on a battle map, and the sealed doors of the abandoned prison.

- The DM puts a chest on any map (or the abandoned prison comes with them), picks its kind, and can
  lock it with a card, hide it, look inside, add a random magic item from their list, or take things out.
- A player whose hero stands next to a chest opens it from /play. In a fight that's their turn and
  uses one of their actions. A locked one needs its card in the hero's Equipment.
- The loot is rolled ONCE, the first time anyone looks inside (the DM peeking counts), and stored.
  Taking an item moves it from the chest onto the hero's sheet, so nothing can be taken twice, and
  an opened chest stays open (and keeps what's left in it) for good, saved like everything else.
- Enemies from the prison drop their gear when they fall: a small case on their square (a "drop").
- Sealed doors (sci-fi prison): a hero next to one opens it with the right card; a hidden wall panel
  opens for anyone who finds it. The DM can open any of them.
"""
import json
import random

from flask import Blueprint, jsonify, request

from . import fields as F
from . import loot as LOOT
from .db import get_db, new_uid, now_iso, tx

bp = Blueprint("chests", __name__)

RARITY_OK = set(LOOT.RARITIES)


def _maps():
    from . import maps as M
    return M


def _settings(conn, campaign_id):
    from .rules import merged_settings
    row = conn.execute("SELECT settings FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    try:
        return merged_settings(json.loads(row["settings"] or "{}") if row else {})
    except ValueError:
        return merged_settings({})


def _decode(row):
    d = dict(row)
    d["loot"] = json.loads(row["loot"]) if row["loot"] is not None else None
    d["added"] = json.loads(row["added"] or "[]")
    d["taken"] = json.loads(row["taken"] or "[]")
    d["opened"] = bool(row["opened"])
    d["hidden"] = bool(row["hidden"])
    return d


def _item_public(it):
    return {k: it.get(k) for k in ("id", "name", "qty", "rarity", "type", "desc", "weight", "unique", "magic") if it.get(k) is not None}


def chests_for(conn, map_id, viewer="dm", m=None):
    """The chests on a map. Players get the ones they can see (not hidden, on a square out of the
    fog), and only what's inside the opened ones."""
    rows = conn.execute("SELECT * FROM chests WHERE map_id = ? ORDER BY id", (map_id,)).fetchall()
    out = []
    for r in rows:
        c = _decode(r)
        info = LOOT.CHESTS.get(c["kind"], LOOT.CHESTS["supply"])
        base = {"id": c["id"], "x": c["x"], "y": c["y"], "kind": c["kind"], "name": c["label"] or info["name"],
                "opened": c["opened"], "locked_by": c["locked_by"], "source": c["source"]}
        if viewer == "dm":
            base.update(hidden=c["hidden"], about=info["about"], opened_by=c["opened_by"], rolled=c["loot"] is not None,
                        loot=[_item_public(i) for i in (c["loot"] if c["loot"] is not None else c["added"])],
                        taken=c["taken"][-30:])
        else:
            if c["hidden"]:
                continue
            if m is not None and m["fog_enabled"] and not _maps().fog_get(m, c["x"], c["y"]):
                continue
            if c["opened"]:
                base["loot"] = [_item_public(i) for i in c["loot"] or []]
                base["opened_by"] = c["opened_by"]
        out.append(base)
    return out


def _row(conn, chest_id):
    r = conn.execute("SELECT * FROM chests WHERE id = ?", (chest_id,)).fetchone()
    if r is None:
        raise F.NotFound("That chest isn't here any more")
    return r


def _ensure_loot(conn, row):
    """Roll what's inside (once). DM-added items come along."""
    c = _decode(row)
    if c["loot"] is not None:
        return c["loot"]
    camp = conn.execute("SELECT campaign_id FROM maps WHERE id = ?", (c["map_id"],)).fetchone()["campaign_id"]
    magic_on = bool(_settings(conn, camp)["loot"].get("magic_items", True))
    items = LOOT.roll_chest(c["kind"], c["seed"], magic_on) if c["kind"] in LOOT.CHESTS else []
    items += c["added"]
    conn.execute("UPDATE chests SET loot = ?, added = '[]', updated_at = ? WHERE id = ?", (json.dumps(items), now_iso(), c["id"]))
    return items


def add_chest(conn, map_id, kind, x, y, locked_by=None, hidden=False, label="", source="placed", loot=None, seed=None):
    if kind not in LOOT.CHESTS:
        raise F.ApiError("Pick a kind of chest")
    if locked_by is None:
        locked_by = LOOT.CHESTS[kind].get("lock", "")
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO chests (uid, map_id, kind, label, x, y, locked_by, hidden, seed, loot, source, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_uid(), map_id, kind, str(label or "")[:80], int(x), int(y), str(locked_by or "")[:80], int(bool(hidden)),
         int(seed if seed is not None else random.SystemRandom().randrange(1, 2 ** 31)),
         json.dumps(loot) if loot is not None else None, source, ts, ts))
    return cur.lastrowid


# ---- the DM -------------------------------------------------------------------------------------

def _dm_reply(map_id, **extra):
    return jsonify(_maps().dm_state(map_id) | extra)


@bp.get("/api/chest-kinds")
def api_kinds():
    return jsonify({"kinds": [{"key": k, "name": v["name"], "about": v["about"], "lock": v.get("lock", "")}
                              for k, v in LOOT.CHESTS.items() if k not in ("drop", "papers", "abort", "escape")],
                    "cards": LOOT.CARDS, "rarities": [{"key": k, "name": LOOT.RARITY_NAME[k]} for k in LOOT.RARITIES]})


@bp.post("/api/maps/<int:map_id>/chests")
def api_add(map_id):
    data = request.get_json(silent=True) or {}
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        try:
            x, y = int(data.get("x")), int(data.get("y"))
        except (TypeError, ValueError):
            raise F.ApiError("Where should it go?")
        if not (0 <= x < m["cols"] and 0 <= y < m["rows"]):
            raise F.ApiError("That's off the map")
        if m["terrain"].get(f"{x},{y}") in M.SOLID:
            raise F.ApiError("That square is solid — put it on open floor")
        if conn.execute("SELECT 1 FROM chests WHERE map_id = ? AND x = ? AND y = ?", (map_id, x, y)).fetchone():
            raise F.ApiError("There's already a chest on that square")
        lock = data.get("locked_by")
        if lock is not None and lock not in ("", *LOOT.CARDS):
            raise F.ApiError("Lock it with a Security keycard, Lab keycard or the Warden's access card (or nothing)")
        cid = add_chest(conn, map_id, str(data.get("kind") or "supply"), x, y, lock, bool(data.get("hidden")), data.get("label") or "")
        M._bump(conn, map_id)
    return _dm_reply(map_id, chest_id=cid), 201


@bp.patch("/api/chests/<int:chest_id>")
def api_patch(chest_id):
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        r = _row(conn, chest_id)
        sets = {}
        if "locked_by" in data:
            if data["locked_by"] not in ("", *LOOT.CARDS):
                raise F.ApiError("Lock it with a Security keycard, Lab keycard or the Warden's access card (or nothing)")
            sets["locked_by"] = data["locked_by"]
        if "hidden" in data:
            sets["hidden"] = int(bool(data["hidden"]))
        if "label" in data:
            sets["label"] = str(data["label"] or "")[:80]
        if "kind" in data:
            if data["kind"] not in LOOT.CHESTS:
                raise F.ApiError("Pick a kind of chest")
            if r["loot"] is not None:
                raise F.ApiError("Its loot is already rolled — make a new chest instead")
            sets["kind"] = data["kind"]
        if sets:
            sets["updated_at"] = now_iso()
            conn.execute(f"UPDATE chests SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), chest_id))
        _maps()._bump(conn, r["map_id"])
    return _dm_reply(r["map_id"])


@bp.delete("/api/chests/<int:chest_id>")
def api_delete(chest_id):
    with tx() as conn:
        r = _row(conn, chest_id)
        conn.execute("DELETE FROM chests WHERE id = ?", (chest_id,))
        _maps()._bump(conn, r["map_id"])
    return _dm_reply(r["map_id"])


@bp.post("/api/chests/<int:chest_id>/roll")
def api_roll(chest_id):
    """The DM looks inside before anyone opens it: the loot is rolled now (and stays)."""
    with tx() as conn:
        r = _row(conn, chest_id)
        _ensure_loot(conn, r)
        _maps()._bump(conn, r["map_id"])
    return _dm_reply(r["map_id"])


@bp.post("/api/chests/<int:chest_id>/magic")
def api_magic(chest_id):
    """Put a random magic item from the DM's list in this chest. {rarity: "" (any) | common ... legendary}"""
    data = request.get_json(silent=True) or {}
    rarity = data.get("rarity") or None
    if rarity is not None and rarity not in RARITY_OK:
        raise F.ApiError("Pick a rarity")
    with tx() as conn:
        r = _row(conn, chest_id)
        item = LOOT.magic_item(rarity, random.SystemRandom())
        if item is None:
            raise F.ApiError("The magic item list is missing (app/magic_items.json)")
        item["id"] = "%08x" % random.getrandbits(32)
        c = _decode(r)
        if c["loot"] is None:
            conn.execute("UPDATE chests SET added = ?, updated_at = ? WHERE id = ?", (json.dumps(c["added"] + [item]), now_iso(), chest_id))
        else:
            conn.execute("UPDATE chests SET loot = ?, updated_at = ? WHERE id = ?", (json.dumps(c["loot"] + [item]), now_iso(), chest_id))
        _maps()._bump(conn, r["map_id"])
    return _dm_reply(r["map_id"], added=_item_public(item))


@bp.delete("/api/chests/<int:chest_id>/items/<item_id>")
def api_remove_item(chest_id, item_id):
    with tx() as conn:
        r = _row(conn, chest_id)
        c = _decode(r)
        col = "loot" if c["loot"] is not None else "added"
        items = c[col]
        if not any(i.get("id") == item_id for i in items):
            raise F.NotFound("That item isn't in the chest")
        conn.execute(f"UPDATE chests SET {col} = ?, updated_at = ? WHERE id = ?",
                     (json.dumps([i for i in items if i.get("id") != item_id]), now_iso(), chest_id))
        _maps()._bump(conn, r["map_id"])
    return _dm_reply(r["map_id"])


# ---- doors (the abandoned prison) ----------------------------------------------------------------

DOORS = ("sealed", "panel")


def _door_room(m, x, y):
    for i, r in enumerate((m.get("dungeon") or {}).get("rooms") or []):
        if r.get("door") == [x, y]:
            return i, r
    return None, None


def open_door(conn, m, x, y, who="The DM"):
    from .dungeon_maps import _reveal_box
    if m["terrain"].get(f"{x},{y}") not in DOORS:
        raise F.ApiError("There's no sealed door there")
    _, room = _door_room(m, x, y)
    m["terrain"][f"{x},{y}"] = "blastdoor"
    conn.execute("UPDATE maps SET terrain = ?, updated_at = ? WHERE id = ?", (json.dumps(m["terrain"]), now_iso(), m["id"]))
    if room:
        _reveal_box(conn, m["id"], room["box"], True)
    from .dungeon_maps import look_around, sight_fight
    look_around(conn, m["id"])
    sight_fight(conn, m)  # whoever's behind the door sees whoever opened it
    _maps()._bump(conn, m["id"])
    return room["name"] if room else "the door"


@bp.post("/api/maps/<int:map_id>/doors")
def api_dm_door(map_id):
    data = request.get_json(silent=True) or {}
    M = _maps()
    with tx() as conn:
        m = M.map_dict(M._map_row(conn, map_id))
        name = open_door(conn, m, int(data.get("x", -1)), int(data.get("y", -1)))
    return _dm_reply(map_id, opened=name)


# ---- players ----------------------------------------------------------------------------------------

def _hero(conn, ident, m):
    """The player's hero on the live map: (token row, character dict)."""
    char_id = ident.get("character_id")
    if not char_id:
        raise F.ApiError("Pick your character first", status=403)
    t = conn.execute("SELECT t.* FROM map_tokens t LEFT JOIN combatants cb ON cb.id = t.combatant_id "
                     "WHERE t.map_id = ? AND (t.character_id = ? OR cb.character_id = ?) LIMIT 1", (m["id"], char_id, char_id)).fetchone()
    if t is None:
        raise F.ApiError("Your hero isn't on this map", status=403)
    ch = F.decode_row(conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone(), F.CHARACTER)
    ch["id"] = char_id
    return t, ch


def next_to(t, x, y):
    """A token (any size) is on or next to square (x, y)."""
    tx0, ty0 = int(round(t["x"])), int(round(t["y"]))
    gx = max(0, x - (tx0 + t["size"] - 1), tx0 - x)
    gy = max(0, y - (ty0 + t["size"] - 1), ty0 - y)
    return max(gx, gy) <= 1


def _live_map(conn, ident):
    M = _maps()
    camp = conn.execute("SELECT live_map_id FROM campaigns WHERE id = ?", (ident["campaign_id"],)).fetchone()
    if not camp or not camp["live_map_id"]:
        raise F.ApiError("There's no map to play on", status=403)
    return M.map_dict(M._map_row(conn, camp["live_map_id"]))


def _fight_action(conn, m, char_id, what):
    """In a fight on this map: only on your own turn, and it uses one of your actions."""
    from .movement import check_action, fight_turn, spend_action
    turn = fight_turn(conn, m, char_id)
    if turn is None:
        return
    if not turn["my_turn"]:
        raise F.ApiError(f"There's a fight on — {what} on your turn", status=403)
    check_action(conn, turn["cb_id"], what)
    spend_action(conn, turn["cb_id"])
    conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), m["encounter_id"]))


def _log(conn, m, text):
    if m.get("encounter_id"):
        enc = conn.execute("SELECT round, status FROM encounters WHERE id = ?", (m["encounter_id"],)).fetchone()
        if enc and enc["status"] != "ended":
            conn.execute("INSERT INTO combat_log (encounter_id, round, kind, message, created_at) VALUES (?, ?, 'system', ?, ?)",
                         (m["encounter_id"], enc["round"], text, now_iso()))


def _player():
    from .play import _player_required
    return _player_required()


@bp.post("/api/play/chests/<int:chest_id>/open")
def api_play_open(chest_id):
    ident = _player()
    with tx() as conn:
        m = _live_map(conn, ident)
        r = _row(conn, chest_id)
        if r["map_id"] != m["id"] or r["hidden"] or (m["fog_enabled"] and not _maps().fog_get(m, r["x"], r["y"])):
            raise F.NotFound("That chest isn't here any more")
        t, ch = _hero(conn, ident, m)
        if not next_to(t, r["x"], r["y"]):
            raise F.ApiError("Walk up to it first: stand next to the chest", status=403)
        name = r["label"] or LOOT.CHESTS.get(r["kind"], LOOT.CHESTS["supply"])["name"]
        silo_kind = r["kind"] in ("abort", "escape")
        if silo_kind:  # the launch bay: refused once it's all over
            from .silo import use
            use(conn, m, r, ch)
        if not r["opened"]:
            if r["locked_by"] and not LOOT.has_item(ch, r["locked_by"]) and not LOOT.has_item(ch, "Omega clearance badge"):
                raise F.ApiError(f"Locked. It needs a {r['locked_by']}", status=403, needs=r["locked_by"])
            _fight_action(conn, m, ch["id"], "open a chest")
            _ensure_loot(conn, r)
            conn.execute("UPDATE chests SET opened = 1, opened_by = ?, opened_at = ?, updated_at = ? WHERE id = ?",
                         (ch["name"], now_iso(), now_iso(), chest_id))
            if not silo_kind:
                _log(conn, m, f"{ch['name']} reads the {name}" if r["kind"] == "papers" else
                     f"{ch['name']} opens the {name}" + (f" with the {r['locked_by']}" if r["locked_by"] else ""))
            _maps()._bump(conn, m["id"])
            if silo_kind:  # the third key turned, or Steven reached: the ending
                from .silo import after_use
                after_use(conn, m, r, ch)
        if r["kind"] == "papers":  # whoever reads it gets it as a handout (once each)
            _read_papers(conn, m, r, ch)
        r = _row(conn, chest_id)
    return jsonify({"chest": next(c for c in chests_for(get_db(), m["id"], "player") if c["id"] == chest_id)})


def _read_papers(conn, m, r, ch):
    from .dungeon import room_at
    from .lab_papers import give_handout
    c = _decode(_row(conn, r["id"]))
    notes = [i for i in (c["loot"] or []) if i.get("type") == "note"]
    if not notes:
        return
    room = room_at((m.get("dungeon") or {}).get("rooms") or [], r["x"], r["y"])
    where = ", ".join(x for x in (m["name"], room["name"] if room else "") if x)
    note = notes[0]
    give_handout(conn, m["campaign_id"], ch["id"], note["name"], note.get("desc") or "", where)  # (pages hear about it like any change)


@bp.post("/api/play/chests/<int:chest_id>/take")
def api_play_take(chest_id):
    """{item: <item id> | "all"}: onto your hero's sheet. Things you can't carry stay in the chest."""
    ident = _player()
    data = request.get_json(silent=True) or {}
    want = data.get("item")
    with tx() as conn:
        m = _live_map(conn, ident)
        r = _row(conn, chest_id)
        if r["map_id"] != m["id"] or not r["opened"]:
            raise F.ApiError("Open it first", status=403)
        t, ch = _hero(conn, ident, m)
        if not next_to(t, r["x"], r["y"]):
            raise F.ApiError("Stand next to the chest to take things out", status=403)
        c = _decode(r)
        items = c["loot"] or []
        pick = items if want == "all" else [i for i in items if i.get("id") == want]
        if not pick:
            raise F.ApiError("Someone already took that" if want != "all" else "It's empty", status=409)
        got, left, why = [], [], []
        for it in items:
            if it not in pick:
                left.append(it)
                continue
            try:
                eq, cur = LOOT.give(ch, it)
            except ValueError as e:
                left.append(it)
                why.append(str(e))
                continue
            ch["equipment"], ch["currency"] = eq, cur
            got.append(it)
        if got:
            conn.execute("UPDATE characters SET equipment = ?, currency = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(ch["equipment"]), json.dumps(ch["currency"]), now_iso(), ch["id"]))
            taken = c["taken"] + [{"id": i["id"], "name": i["name"], "by": ch["name"], "at": now_iso()} for i in got]
            conn.execute("UPDATE chests SET loot = ?, taken = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(left), json.dumps(taken[-200:]), now_iso(), chest_id))
            _log(conn, m, f"{ch['name']} takes " + ", ".join(i["name"] for i in got))
            _maps()._bump(conn, m["id"])
        elif why:
            raise F.ApiError(why[0], status=403)
    return jsonify({"took": [_item_public(i) for i in got], "left": [_item_public(i) for i in left], "why": why})


@bp.post("/api/play/doors")
def api_play_door():
    """Open a sealed door (with its card) or push a hidden panel, standing next to it. {x, y}"""
    ident = _player()
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        m = _live_map(conn, ident)
        try:
            x, y = int(data.get("x")), int(data.get("y"))
        except (TypeError, ValueError):
            raise F.ApiError("Which door?")
        if m["terrain"].get(f"{x},{y}") not in DOORS or (m["fog_enabled"] and not _maps().fog_get(m, x, y)):
            raise F.ApiError("There's no sealed door there")
        t, ch = _hero(conn, ident, m)
        if not next_to(t, x, y):
            raise F.ApiError("Walk up to the door first", status=403)
        _, room = _door_room(m, x, y)
        needs = (room or {}).get("needs", "")
        if needs and not LOOT.has_item(ch, needs) and not LOOT.has_item(ch, "Omega clearance badge"):
            raise F.ApiError(f"Sealed. It needs a {needs}", status=403, needs=needs)
        _fight_action(conn, m, ch["id"], "open a door")
        name = open_door(conn, m, x, y)
        _log(conn, m, f"{ch['name']} opens the way into {name}" + (f" with the {needs}" if needs else ""))
    return jsonify({"opened": name})


# ---- enemies drop their gear ---------------------------------------------------------------------

def enemy_down(ctx, c):
    """A prison enemy fell: what it carried lands on its square as a small case (once per enemy)."""
    sb = c.get("statblock") or {}
    base = sb.get("base_name") or c["name"]
    if sb.get("dropped") or (base not in LOOT.DROPS and not sb.get("carries")):
        return None
    conn = ctx.conn
    sb["dropped"] = True
    conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), c["id"]))
    items = LOOT.roll_drop(base, random.SystemRandom().randrange(1, 2 ** 31), sb.get("carries") or [])
    if not items:
        return None
    from .movement import _token_of
    made = None
    for mp in conn.execute("SELECT id FROM maps WHERE encounter_id = ?", (ctx.enc["id"],)).fetchall():
        t = _token_of(conn, mp["id"], c["id"])
        if not t:
            continue
        x, y = int(round(t["x"])), int(round(t["y"]))
        while conn.execute("SELECT 1 FROM chests WHERE map_id = ? AND x = ? AND y = ?", (mp["id"], x, y)).fetchone():
            x += 1  # (two fell on one square)
        made = add_chest(conn, mp["id"], "drop", x, y, "", False, f"{c['name']}'s gear", "drop", loot=items)
        _maps()._bump(conn, mp["id"])
        break
    if made:
        ctx.log("system", f"{c['name']} drops: " + ", ".join(i["name"] for i in items))
    return made
