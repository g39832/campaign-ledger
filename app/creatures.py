"""Reusable creature library.

Encounters copy a creature's stat block when an enemy is added, so editing or
deleting a library entry never changes enemies already placed in encounters.
"""
import re

from flask import Blueprint, jsonify, request

from . import fields as F
from .db import get_db, new_uid, now_iso, tx
from .rules import ABILITIES

bp = Blueprint("creatures", __name__, url_prefix="/api")


def creature_dict(row):
    return F.decode_row(row, F.CREATURE) | {"campaign_id": row["campaign_id"], "id": row["id"],
                                            "portrait": row["portrait"] if "portrait" in row.keys() else None}


def list_creatures(campaign_id=None, q=""):
    sql = "SELECT * FROM creatures WHERE (campaign_id IS NULL OR campaign_id = ?)"
    params = [campaign_id]
    if q:
        sql += " AND (name LIKE ? OR creature_type LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name COLLATE NOCASE"
    return [creature_dict(r) for r in get_db().execute(sql, params).fetchall()]


@bp.get("/creatures")
def api_list():
    cid = request.args.get("campaign_id", type=int)
    return jsonify({"creatures": list_creatures(cid, request.args.get("q", "").strip())})


@bp.post("/creatures")
def api_create():
    data = dict(request.get_json(silent=True) or {})
    campaign_id = data.pop("campaign_id", None)
    values = F.validate_new(F.CREATURE, data)
    if not values.get("name", "").strip():
        raise F.ApiError("Name the creature")
    values.setdefault("abilities", {a: 10 for a in ABILITIES})
    ts = now_iso()
    with tx() as conn:
        new_id = F.insert(conn, "creatures", F.CREATURE, values,
                          {"uid": new_uid(), "campaign_id": campaign_id, "created_at": ts, "updated_at": ts})
    row = get_db().execute("SELECT * FROM creatures WHERE id = ?", (new_id,)).fetchone()
    return jsonify({"creature": creature_dict(row)}), 201


def boss_party(conn, campaign_id):
    """The party a boss is made for: how many heroes the campaign has and their average level."""
    rows = conn.execute("SELECT level FROM characters WHERE campaign_id = ? AND kind = 'pc' AND archived = 0", (campaign_id,)).fetchall() if campaign_id else []
    return {"size": len(rows) or 4, "level": round(sum(r["level"] or 1 for r in rows) / len(rows)) if rows else 3}


_DICE = re.compile(r"(\d*)d(\d+)", re.I)
_SMALLER = {12: 10, 10: 8, 8: 6, 6: 4}
_COOLDOWN = re.compile(r",?\s*\d+\s*-?\s*(?:turns?|rounds?)\s*(?:of\s*)?cool\s*-?\s*down", re.I)
_AREA = re.compile(r"\b(?:cone|line|cube|square|radius|sphere|circle|cylinder|emanation)\b", re.I)


def legendary_from(attacks):
    """Legendary actions made from a monster's own attacks: its first two plain ones (no area, no
    cooldown), with lighter damage (half the dice, or one die size down)."""
    def lighter(m):
        n, s = int(m.group(1) or 1), int(m.group(2))
        return f"{n // 2}d{s}" if n > 1 else f"1d{_SMALLER.get(s, s)}"
    out = []
    for line in str(attacks or "").splitlines():
        line = line.strip()
        if not line or not _DICE.search(line) or _AREA.search(line) or _COOLDOWN.search(line) or "heal" in line.lower():
            continue
        out.append(_DICE.sub(lighter, line, count=1))
        if len(out) == 2:
            break
    return "\n".join(out)


@bp.get("/creatures/boss-party")
def api_boss_party():
    return jsonify(boss_party(get_db(), request.args.get("campaign_id", type=int)))


@bp.post("/creatures/<int:cr_id>/make-boss")
def api_make_boss(cr_id):
    """Make a boss copy of a monster, scaled for the party: HP x the party size (at least x2),
    +1 AC (+2 from level 5), legendary actions from its own attacks, legendary resistance by level
    (1, 2 from level 5, 3 from level 11) and phase 2 on. The original stays as it was.
    {campaign_id, party_size, party_level}: missing ones come from the campaign's heroes."""
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        row = conn.execute("SELECT * FROM creatures WHERE id = ?", (cr_id,)).fetchone()
        if row is None:
            raise F.NotFound("Creature not found")
        party = boss_party(conn, data.get("campaign_id") or row["campaign_id"])
        try:
            size = max(1, min(12, int(data.get("party_size") or party["size"])))
            level = max(1, min(20, int(data.get("party_level") or party["level"])))
        except (TypeError, ValueError):
            raise F.ApiError("Party size and level must be numbers")
        v = {k: val for k, val in F.decode_row(row, F.CREATURE).items() if k in F.CREATURE}
        v.update(name=f"{v['name']} (Boss)"[:200], boss=True, max_hp=min(99999, (v["max_hp"] or 1) * max(2, size)),
                 ac=min(99, (v["ac"] or 10) + (2 if level >= 5 else 1)), legendary=legendary_from(v["attacks"]), legendary_per_round=3,
                 legendary_resistance=3 if level >= 11 else 2 if level >= 5 else 1, has_phase2=True)
        ts = now_iso()
        new_id = F.insert(conn, "creatures", F.CREATURE, v,
                          {"uid": new_uid(), "campaign_id": row["campaign_id"], "created_at": ts, "updated_at": ts})
        if row["portrait"]:
            conn.execute("UPDATE creatures SET portrait = ? WHERE id = ?", (row["portrait"], new_id))
    new = get_db().execute("SELECT * FROM creatures WHERE id = ?", (new_id,)).fetchone()
    return jsonify({"creature": creature_dict(new), "party": {"size": size, "level": level},
                    "from": {"max_hp": row["max_hp"], "ac": row["ac"]}}), 201


@bp.patch("/creatures/<int:cr_id>")
def api_patch(cr_id):
    changes = (request.get_json(silent=True) or {}).get("changes")
    with tx() as conn:
        if isinstance(changes, dict) and "name" in changes and not str(changes["name"].get("to", "")).strip():
            raise F.ApiError("Name can't be empty")
        F.cas_patch(conn, "creatures", F.CREATURE, cr_id, changes)
    row = get_db().execute("SELECT * FROM creatures WHERE id = ?", (cr_id,)).fetchone()
    return jsonify({"creature": creature_dict(row)})


@bp.post("/creatures/<int:cr_id>/portrait")
def api_portrait(cr_id):
    """A picture for the creature (its icon): shown in the library, in fights and on its map tokens,
    including enemies of its kind already in a fight."""
    import os
    import uuid
    from flask import current_app
    from .characters import PORTRAIT_TYPES
    if get_db().execute("SELECT 1 FROM creatures WHERE id = ?", (cr_id,)).fetchone() is None:
        raise F.NotFound("Creature not found")
    f = request.files.get("file")
    if f is None or not f.filename:
        raise F.ApiError("Choose an image file")
    ext = PORTRAIT_TYPES.get(f.mimetype)
    if ext is None:
        raise F.ApiError("Pictures must be PNG, JPEG, WebP or GIF")
    name = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(current_app.config["UPLOAD_DIR"], name))
    with tx() as conn:
        conn.execute("UPDATE creatures SET portrait = ?, updated_at = ? WHERE id = ?", (name, now_iso(), cr_id))
        _touch_fights(conn, cr_id)
    # old files are kept: backups taken earlier may still use them
    return jsonify({"creature": creature_dict(get_db().execute("SELECT * FROM creatures WHERE id = ?", (cr_id,)).fetchone())})


@bp.delete("/creatures/<int:cr_id>/portrait")
def api_portrait_clear(cr_id):
    with tx() as conn:
        conn.execute("UPDATE creatures SET portrait = NULL, updated_at = ? WHERE id = ?", (now_iso(), cr_id))
        _touch_fights(conn, cr_id)
    row = get_db().execute("SELECT * FROM creatures WHERE id = ?", (cr_id,)).fetchone()
    if row is None:
        raise F.NotFound("Creature not found")
    return jsonify({"creature": creature_dict(row)})


def _touch_fights(conn, cr_id):
    """Fights and maps with this creature's enemies redraw with the new picture."""
    conn.execute("UPDATE encounters SET rev = rev + 1 WHERE status != 'ended' AND id IN (SELECT encounter_id FROM combatants WHERE creature_id = ?)", (cr_id,))
    conn.execute("UPDATE maps SET rev = rev + 1 WHERE id IN (SELECT t.map_id FROM map_tokens t JOIN combatants cb ON cb.id = t.combatant_id WHERE cb.creature_id = ?)", (cr_id,))


@bp.delete("/creatures/<int:cr_id>")
def api_delete(cr_id):
    with tx() as conn:
        if conn.execute("SELECT 1 FROM creatures WHERE id = ?", (cr_id,)).fetchone() is None:
            raise F.NotFound("Creature not found")
        conn.execute("DELETE FROM creatures WHERE id = ?", (cr_id,))
    return jsonify({"deleted": cr_id})


# ---- Monster Book: ready-made stat blocks to copy into the library ---------------

def _library_names(conn, campaign_id):
    rows = conn.execute("SELECT name FROM creatures WHERE campaign_id IS NULL OR campaign_id = ?", (campaign_id,)).fetchall()
    return {r["name"].strip().lower() for r in rows}


@bp.get("/monster-book")
def api_monster_book():
    from .monster_book import ATTRIBUTION, MONSTERS, cr_value
    have = _library_names(get_db(), request.args.get("campaign_id", type=int))
    items = [{"name": m["name"], "creature_type": m["creature_type"], "cr": m["cr"], "max_hp": m["max_hp"], "ac": m["ac"],
              "in_library": m["name"].lower() in have} for m in MONSTERS]
    items.sort(key=lambda m: (cr_value(m["cr"]), m["name"]))
    return jsonify({"monsters": items, "attribution": ATTRIBUTION})


@bp.post("/monster-book/add")
def api_monster_book_add():
    """Copy chosen Monster Book entries into the shared creature library.
    Monsters already in the library (same name) are skipped, never duplicated."""
    from .monster_book import BY_NAME
    data = request.get_json(silent=True) or {}
    names = data.get("names")
    if not isinstance(names, list) or not names or len(names) > 200 or not all(isinstance(n, str) for n in names):
        raise F.ApiError("Choose at least one monster")
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        raise F.ApiError(f"Not in the Monster Book: {', '.join(map(str, unknown[:3]))}")
    added, skipped = [], []
    ts = now_iso()
    with tx() as conn:
        have = _library_names(conn, data.get("campaign_id"))
        for name in dict.fromkeys(names):  # keep order, drop repeats
            if name.lower() in have:
                skipped.append(name)
                continue
            values = F.validate_new(F.CREATURE, BY_NAME[name])
            F.insert(conn, "creatures", F.CREATURE, values,
                     {"uid": new_uid(), "campaign_id": None, "created_at": ts, "updated_at": ts})
            have.add(name.lower())
            added.append(name)
    return jsonify({"added": added, "skipped": skipped, "creatures": list_creatures(data.get("campaign_id"))})
