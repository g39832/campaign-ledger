"""Encounters, initiative, HP and conditions.

Player characters and character NPCs in an encounter don't keep their own
copy of HP, AC, conditions or status: those live on the character row, so the
combat screen and the character sheet always show the same numbers. Enemies
keep their own per-instance values on the combatant row, plus a frozen copy of
the creature's stat block taken when they were added.
"""
import json
import random
import uuid

from flask import Blueprint, jsonify, request

from . import fields as F
from .campaigns import get_campaign
from .db import claim_op, get_db, new_uid, now_iso, tx
from .rules import apply_damage, apply_heal, apply_temp, derived, initiative_sort_key, roll_d20, is_healing, spell_info

bp = Blueprint("combat", __name__, url_prefix="/api")

LINKED_FIELDS = {"ac", "status", "death_successes", "death_failures"}
VITAL_KEYS = ("hp", "max_hp", "temp_hp", "status", "death_successes", "death_failures")
rng = random.SystemRandom()


# ---- reading ----------------------------------------------------------------

def _combatant_rows(conn, enc_id):
    return conn.execute(
        """SELECT c.*, ch.name AS ch_name, ch.current_hp AS ch_hp, ch.max_hp AS ch_max, ch.temp_hp AS ch_temp,
                  ch.ac AS ch_ac, ch.status AS ch_status, ch.conditions AS ch_conditions,
                  ch.death_successes AS ch_ds, ch.death_failures AS ch_df, ch.portrait AS ch_portrait,
                  ch.class_name AS ch_class, ch.level AS ch_level, ch.exhaustion AS ch_exhaustion,
                  ch.attacks AS ch_attacks
           FROM combatants c LEFT JOIN characters ch ON ch.id = c.character_id
           WHERE c.encounter_id = ? ORDER BY c.sort_order, c.id""",
        (enc_id,),
    ).fetchall()


def _combatant_dict(r):
    linked = r["character_id"] is not None and r["ch_name"] is not None
    d = {
        "id": r["id"], "kind": r["kind"], "character_id": r["character_id"], "creature_id": r["creature_id"],
        "linked": linked, "init_roll": r["init_roll"], "init_mod": r["init_mod"], "sort_order": r["sort_order"],
        "notes": r["notes"], "statblock": json.loads(r["statblock"] or "{}"), "hidden": bool(r["hidden"]),
    }
    if linked:
        d.update(name=r["ch_name"], hp=r["ch_hp"], max_hp=r["ch_max"], temp_hp=r["ch_temp"], ac=r["ch_ac"],
                 status=r["ch_status"], conditions=json.loads(r["ch_conditions"]),
                 death_successes=r["ch_ds"], death_failures=r["ch_df"], portrait=r["ch_portrait"],
                 subtitle=" ".join(x for x in (r["ch_class"] or "", f"{r['ch_level']}" if r["ch_class"] else "") if x),
                 exhaustion=r["ch_exhaustion"],
                 # Attack names (in sheet order) so combat can offer the sheet's Hit / Dmg rolls.
                 attacks=[{"name": (a.get("name") or "Attack").strip() or "Attack", "has_hit": bool(str(a.get("bonus") or "").strip()),
                           "has_dmg": bool(str(a.get("damage") or "").strip()), "heal": is_healing(a)}
                          for a in json.loads(r["ch_attacks"] or "[]") if isinstance(a, dict)])
    else:
        d.update(name=r["name"], hp=r["current_hp"], max_hp=r["max_hp"], temp_hp=r["temp_hp"], ac=r["ac"],
                 status=r["status"], conditions=json.loads(r["conditions"]), death_successes=0,
                 death_failures=0, portrait=None, subtitle=d["statblock"].get("creature_type", ""), exhaustion=0)
    return d


def _encounter_row(conn, enc_id):
    row = conn.execute("SELECT * FROM encounters WHERE id = ?", (enc_id,)).fetchone()
    if row is None:
        raise F.NotFound("Encounter not found")
    return row


def _add_spells(conn, c):
    """Spells that do something (damage, healing, an effect) plus the caster's save DC
    and spell attack, so combat can offer them next to weapon attacks."""
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (c["character_id"],)).fetchone()
    ch = F.decode_row(row, F.CHARACTER)
    spell = derived(ch)["spell"]
    c["spellcasting"] = {"dc": spell["dc"], "attack": spell["attack"]} if spell else None
    c["spells"] = [dict(spell_info(s), index=i) for i, s in enumerate(ch.get("spells") or [])
                   if spell_info(s)["effect"]]


def encounter_state(enc_id, conn=None, log_limit=400):
    conn = conn or get_db()
    enc = dict(_encounter_row(conn, enc_id))
    combatants = [_combatant_dict(r) for r in _combatant_rows(conn, enc_id)]
    for c in combatants:
        if c["linked"]:
            _add_spells(conn, c)
    log = [dict(r) for r in conn.execute(
        "SELECT * FROM (SELECT * FROM combat_log WHERE encounter_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
        (enc_id, log_limit),
    ).fetchall()]
    total_log = conn.execute("SELECT COUNT(*) FROM combat_log WHERE encounter_id = ?", (enc_id,)).fetchone()[0]
    undo = conn.execute(
        "SELECT id, label FROM hp_changes WHERE encounter_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1",
        (enc_id,),
    ).fetchone()
    settings = get_campaign(enc["campaign_id"])["settings"]["combat"]
    return {
        "encounter": enc,
        "combatants": combatants,
        "log": log,
        "log_total": total_log,
        "undo": dict(undo) if undo else None,
        "settings": settings,
    }


def list_encounters(campaign_id):
    rows = get_db().execute(
        """SELECT e.*, (SELECT COUNT(*) FROM combatants WHERE encounter_id = e.id) AS combatant_count,
                  (SELECT COUNT(*) FROM combatants WHERE encounter_id = e.id AND kind = 'enemy') AS enemy_count
           FROM encounters e WHERE campaign_id = ?
           ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'planning' THEN 1 ELSE 2 END, e.updated_at DESC""",
        (campaign_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- writing helpers ----------------------------------------------------------

class Ctx:
    """Everything a mutation needs: the connection, the encounter row and
    a helper to write log lines stamped with the current round and turn."""

    def __init__(self, conn, enc_id):
        self.conn = conn
        self.enc = dict(_encounter_row(conn, enc_id))
        self.settings = get_campaign(self.enc["campaign_id"])["settings"]["combat"]

    def combatants(self):
        return [_combatant_dict(r) for r in _combatant_rows(self.conn, self.enc["id"])]

    def combatant(self, cid):
        for c in self.combatants():
            if c["id"] == cid:
                return c
        raise F.NotFound("That combatant isn't in this encounter")

    def current_name(self):
        if not self.enc["current_id"]:
            return ""
        row = self.conn.execute(
            "SELECT COALESCE(ch.name, c.name) FROM combatants c LEFT JOIN characters ch ON ch.id = c.character_id "
            "WHERE c.id = ?", (self.enc["current_id"],)).fetchone()
        return row[0] if row else ""

    def log(self, kind, message):
        self.conn.execute(
            "INSERT INTO combat_log (encounter_id, round, turn_name, kind, message, created_at) VALUES (?,?,?,?,?,?)",
            (self.enc["id"], self.enc["round"], self.current_name(), kind, message, now_iso()),
        )

    def save_enc(self, **fields):
        self.enc.update(fields)
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE encounters SET {sets} WHERE id = ?", list(fields.values()) + [self.enc["id"]])

    def set_vitals(self, c, **v):
        """Write vitals to the character (linked) or the combatant (enemy)."""
        if c["linked"]:
            m = {"hp": "current_hp", "max_hp": "max_hp", "temp_hp": "temp_hp", "status": "status",
                 "conditions": "conditions", "death_successes": "death_successes",
                 "death_failures": "death_failures", "ac": "ac"}
            table, key = "characters", c["character_id"]
            v = {m[k]: val for k, val in v.items()}
            v["updated_at"] = now_iso()
        else:
            m = {"hp": "current_hp", "max_hp": "max_hp", "temp_hp": "temp_hp", "status": "status",
                 "conditions": "conditions", "ac": "ac"}
            table, key = "combatants", c["id"]
            v = {m[k]: val for k, val in v.items() if k in m}
        if "conditions" in v:
            v["conditions"] = json.dumps(v["conditions"])
        if v:
            sets = ", ".join(f"{k} = ?" for k in v)
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", list(v.values()) + [key])
        if c["linked"]:
            # Other open encounters with this character should refresh too.
            self.conn.execute(
                "UPDATE encounters SET rev = rev + 1 WHERE status != 'ended' AND id != ? AND id IN "
                "(SELECT encounter_id FROM combatants WHERE character_id = ?)",
                (self.enc["id"], c["character_id"]))


def mutate(enc_id, fn, op_id=None):
    with tx() as conn:
        ctx = Ctx(conn, enc_id)
        if claim_op(conn, op_id):
            fn(ctx)
            conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), enc_id))
            conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (now_iso(), ctx.enc["campaign_id"]))
    return jsonify(encounter_state(enc_id))


def _body():
    return request.get_json(silent=True) or {}


def _enc_of_combatant(cid):
    row = get_db().execute("SELECT encounter_id FROM combatants WHERE id = ?", (cid,)).fetchone()
    if row is None:
        raise F.NotFound("Combatant not found")
    return row["encounter_id"]


def _int(data, key, lo=None, hi=None, default=None):
    v = data.get(key, default)
    if v is None or v == "":
        if default is not None:
            return default
        raise F.ApiError(f"{key} is required")
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise F.ApiError(f"{key} must be a whole number")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise F.ApiError(f"{key} must be between {lo} and {hi}")
    return v


# ---- encounter lifecycle ----------------------------------------------------

@bp.get("/campaigns/<int:cid>/encounters")
def api_list(cid):
    return jsonify({"encounters": list_encounters(cid)})


@bp.post("/campaigns/<int:cid>/encounters")
def api_create(cid):
    data = _body()
    get_campaign(cid)
    values = F.validate_new(F.ENCOUNTER, {k: data[k] for k in ("name", "location", "notes") if k in data})
    if not values.get("name", "").strip():
        raise F.ApiError("Name the encounter")
    ts = now_iso()
    with tx() as conn:
        eid = F.insert(conn, "encounters", F.ENCOUNTER, values,
                       {"uid": new_uid(), "campaign_id": cid, "created_at": ts, "updated_at": ts})
        conn.execute(
            "INSERT INTO combat_log (encounter_id, round, kind, message, created_at) VALUES (?, 0, 'system', ?, ?)",
            (eid, f"Encounter “{values['name']}” created", ts))
    return jsonify(encounter_state(eid)), 201


@bp.get("/encounters/<int:eid>")
def api_get(eid):
    return jsonify(encounter_state(eid))


@bp.get("/encounters/<int:eid>/rev")
def api_rev(eid):
    row = _encounter_row(get_db(), eid)
    return jsonify({"rev": row["rev"]})


@bp.patch("/encounters/<int:eid>")
def api_patch(eid):
    changes = _body().get("changes")

    def fn(ctx):
        if isinstance(changes, dict) and "name" in changes and not str(changes["name"].get("to", "")).strip():
            raise F.ApiError("Name can't be empty")
        F.cas_patch(ctx.conn, "encounters", F.ENCOUNTER, eid, changes)
    return mutate(eid, fn)


@bp.delete("/encounters/<int:eid>")
def api_delete(eid):
    with tx() as conn:
        enc = _encounter_row(conn, eid)
        if enc["status"] != "planning":
            raise F.ApiError("Only encounters that were never started can be deleted. End it instead — it stays in the history.")
        conn.execute("DELETE FROM journal_links WHERE target_type = 'encounter' AND target_id = ?", (eid,))
        conn.execute("DELETE FROM encounters WHERE id = ?", (eid,))
    return jsonify({"deleted": eid})


def _first_eligible(ctx, order):
    skip = set(ctx.settings["skip_statuses"])
    for c in order:
        if c["status"] not in skip:
            return c
    return order[0] if order else None


@bp.post("/encounters/<int:eid>/start")
def api_start(eid):
    def fn(ctx):
        if ctx.enc["status"] == "active":
            raise F.ApiError("This encounter is already running")
        order = ctx.combatants()
        if not order:
            raise F.ApiError("Add combatants before starting")
        if ctx.settings["auto_sort"]:
            _resort(ctx)
            order = ctx.combatants()
        first = _first_eligible(ctx, order)
        ctx.save_enc(status="active", round=1, current_id=first["id"], started_at=now_iso(), ended_at=None)
        ctx.log("system", "Combat begins — round 1")
        ctx.log("turn", f"{first['name']}'s turn")
        _tick(ctx, first["id"], "start")
    return mutate(eid, fn, _body().get("op_id"))


@bp.post("/encounters/<int:eid>/end")
def api_end(eid):
    def fn(ctx):
        if ctx.enc["status"] == "ended":
            raise F.ApiError("This encounter has already ended")
        ctx.save_enc(status="ended", ended_at=now_iso())
        ctx.log("system", f"Encounter ended after {ctx.enc['round']} round{'s' if ctx.enc['round'] != 1 else ''}")
    return mutate(eid, fn, _body().get("op_id"))


@bp.post("/encounters/<int:eid>/reopen")
def api_reopen(eid):
    def fn(ctx):
        if ctx.enc["status"] != "ended":
            raise F.ApiError("Only ended encounters can be reopened")
        if not ctx.combatants():
            ctx.save_enc(status="planning", ended_at=None)
        else:
            ctx.save_enc(status="active", ended_at=None, round=max(1, ctx.enc["round"]))
            if not ctx.enc["current_id"]:
                ctx.save_enc(current_id=_first_eligible(ctx, ctx.combatants())["id"])
        ctx.log("system", f"Encounter reopened at round {ctx.enc['round']}")
    return mutate(eid, fn, _body().get("op_id"))


# ---- turns ----------------------------------------------------------------------

def _step(ctx, direction):
    order = ctx.combatants()
    if not order:
        raise F.ApiError("No combatants")
    if ctx.enc["status"] != "active":
        raise F.ApiError("Start the encounter first")
    skip = set(ctx.settings["skip_statuses"])
    ids = [c["id"] for c in order]
    n = len(order)
    idx = ids.index(ctx.enc["current_id"]) if ctx.enc["current_id"] in ids else (-1 if direction > 0 else 0)
    chosen, wrapped = None, False
    for step in range(1, n + 1):
        raw = idx + step * direction
        j = raw % n
        if raw >= n or raw < 0:
            wrapped = True
        if order[j]["status"] not in skip:
            chosen = order[j]
            break
    if chosen is None:  # everyone is skipped; just move one place
        raw = idx + direction
        wrapped = raw >= n or raw < 0
        chosen = order[raw % n]
    return chosen, wrapped


@bp.post("/encounters/<int:eid>/next")
def api_next(eid):
    def fn(ctx):
        prev_id = ctx.enc["current_id"]
        chosen, wrapped = _step(ctx, 1)
        if prev_id:
            _tick(ctx, prev_id, "end")
        if wrapped:
            ctx.save_enc(round=ctx.enc["round"] + 1, current_id=None)
            ctx.log("round", f"Round {ctx.enc['round']} begins")
        ctx.save_enc(current_id=chosen["id"])
        ctx.log("turn", f"{chosen['name']}'s turn")
        _tick(ctx, chosen["id"], "start")
    return mutate(eid, fn, _body().get("op_id"))


@bp.post("/encounters/<int:eid>/prev")
def api_prev(eid):
    def fn(ctx):
        chosen, wrapped = _step(ctx, -1)
        if wrapped:
            if ctx.enc["round"] <= 1:
                raise F.ApiError("Already at the first turn of round 1")
            ctx.save_enc(round=ctx.enc["round"] - 1)
        ctx.save_enc(current_id=chosen["id"])
        ctx.log("turn", f"Turn moved back to {chosen['name']} (round {ctx.enc['round']}); effect durations were not rewound")
    return mutate(eid, fn, _body().get("op_id"))


@bp.post("/encounters/<int:eid>/set-turn")
def api_set_turn(eid):
    data = _body()

    def fn(ctx):
        if ctx.enc["status"] != "active":
            raise F.ApiError("Start the encounter first")
        c = ctx.combatant(_int(data, "combatant_id"))
        ctx.save_enc(current_id=c["id"])
        ctx.log("turn", f"DM set the turn to {c['name']}")
    return mutate(eid, fn, data.get("op_id"))


def _tick(ctx, owner_id, phase):
    """Count down effects tied to owner_id's turn start/end. An effect that
    runs out is removed only if it was marked auto-expire; otherwise it is
    flagged so the DM decides. Either way it is written to the log."""
    for c in ctx.combatants():
        conds = c["conditions"]
        changed = False
        keep = []
        for cond in conds:
            if (cond.get("encounter_id") == ctx.enc["id"] and cond.get("tick_on") == owner_id
                    and cond.get("tick") == phase and cond.get("rounds_left") is not None
                    and not cond.get("expired")):
                cond["rounds_left"] -= 1
                changed = True
                if cond["rounds_left"] <= 0:
                    cond["rounds_left"] = 0
                    if cond.get("auto_expire"):
                        ctx.log("condition", f"{cond['name']} on {c['name']} expired and was removed")
                        continue
                    cond["expired"] = True
                    ctx.log("condition", f"{cond['name']} on {c['name']} has run its duration — DM to confirm removal")
            keep.append(cond)
        if changed:
            ctx.set_vitals(c, conditions=keep)


# ---- combatants -----------------------------------------------------------

def _next_sort(ctx):
    row = ctx.conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM combatants WHERE encounter_id = ?",
                           (ctx.enc["id"],)).fetchone()
    return row[0]


def _instance_names(ctx, base, count):
    existing = [c for c in ctx.combatants() if c["statblock"].get("base_name") == base and not c["linked"]]
    nums = []
    for c in existing:
        tail = c["name"][len(base):].strip()
        nums.append(int(tail) if tail.isdigit() else 1)
    start = max(nums) + 1 if nums else 1
    if count == 1 and not existing:
        return [base]
    if len(existing) == 1 and existing[0]["name"] == base:
        # The lone unnumbered one becomes "1" so instances stay distinguishable.
        ctx.conn.execute("UPDATE combatants SET name = ? WHERE id = ?", (f"{base} 1", existing[0]["id"]))
        start = 2
    return [f"{base} {start + i}" for i in range(count)]


def _insert_enemy(ctx, name, statblock, max_hp, ac, init_mod, creature_id=None):
    ctx.conn.execute(
        """INSERT INTO combatants (uid, encounter_id, creature_id, kind, name, init_mod, sort_order, max_hp,
           current_hp, ac, statblock, created_at) VALUES (?, ?, ?, 'enemy', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_uid(), ctx.enc["id"], creature_id, name, init_mod, _next_sort(ctx), max_hp, max_hp, ac,
         json.dumps(statblock), now_iso()))


@bp.post("/encounters/<int:eid>/combatants")
def api_add(eid):
    data = _body()

    def fn(ctx):
        added = []
        for char_id in data.get("characters") or []:
            ch = ctx.conn.execute("SELECT * FROM characters WHERE id = ? AND campaign_id = ?",
                                  (int(char_id), ctx.enc["campaign_id"])).fetchone()
            if ch is None:
                raise F.ApiError("Character not found in this campaign")
            if ctx.conn.execute("SELECT 1 FROM combatants WHERE encounter_id = ? AND character_id = ?",
                                (eid, ch["id"])).fetchone():
                continue
            chd = F.decode_row(ch, F.CHARACTER)
            ctx.conn.execute(
                """INSERT INTO combatants (uid, encounter_id, character_id, kind, name, init_mod, init_roll,
                   sort_order, max_hp, current_hp, ac, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_uid(), eid, ch["id"], ch["kind"], ch["name"], derived(chd)["initiative"], ch["initiative_roll"],
                 _next_sort(ctx), ch["max_hp"], ch["current_hp"], ch["ac"], now_iso()))
            added.append(ch["name"])

        if data.get("creature_id"):
            cr = ctx.conn.execute("SELECT * FROM creatures WHERE id = ?", (int(data["creature_id"]),)).fetchone()
            if cr is None:
                raise F.ApiError("Creature not found")
            count = _int(data, "count", 1, 50, default=1)
            block = F.decode_row(cr, F.CREATURE)
            statblock = {k: block[k] for k in F.CREATURE if k not in ("name",)}
            statblock["base_name"] = cr["name"]
            for name in _instance_names(ctx, cr["name"], count):
                _insert_enemy(ctx, name, statblock, cr["max_hp"], cr["ac"], cr["initiative_mod"], cr["id"])
                added.append(name)

        quick = data.get("quick")
        if quick:
            name = str(quick.get("name", "")).strip()[:200]
            if not name:
                raise F.ApiError("Give the enemy a name")
            max_hp = _int(quick, "max_hp", 1, 99999)
            ac = _int(quick, "ac", 0, 99, default=10)
            init_mod = _int(quick, "init_mod", -50, 50, default=0)
            count = _int(quick, "count", 1, 50, default=1)
            creature_id = None
            if quick.get("save_to_library"):
                ts = now_iso()
                creature_id = F.insert(ctx.conn, "creatures", F.CREATURE,
                                       {"name": name, "max_hp": max_hp, "ac": ac, "initiative_mod": init_mod,
                                        "creature_type": str(quick.get("creature_type", ""))[:200]},
                                       {"uid": new_uid(), "campaign_id": None, "created_at": ts, "updated_at": ts})
            statblock = {"base_name": name, "creature_type": str(quick.get("creature_type", ""))[:200],
                         "initiative_mod": init_mod, "max_hp": max_hp, "ac": ac}
            for n in _instance_names(ctx, name, count):
                _insert_enemy(ctx, n, statblock, max_hp, ac, init_mod, creature_id)
                added.append(n)

        if not added:
            raise F.ApiError("Nothing new to add")
        ctx.log("roster", f"Added {', '.join(added)}")
        if ctx.settings["auto_sort"]:
            _resort(ctx)
    return mutate(eid, fn, data.get("op_id"))


@bp.delete("/combatants/<int:cid>")
def api_remove(cid):
    eid = _enc_of_combatant(cid)

    def fn(ctx):
        c = ctx.combatant(cid)
        if ctx.enc["current_id"] == cid:
            order = ctx.combatants()
            if len(order) > 1:
                chosen, _ = _step(ctx, 1) if ctx.enc["status"] == "active" else (None, False)
                if chosen and chosen["id"] == cid:
                    chosen = next(o for o in order if o["id"] != cid)
                ctx.save_enc(current_id=chosen["id"] if chosen else None)
            else:
                ctx.save_enc(current_id=None)
        ctx.conn.execute("UPDATE hp_changes SET combatant_id = NULL WHERE combatant_id = ?", (cid,))
        ctx.conn.execute("DELETE FROM combatants WHERE id = ?", (cid,))
        ctx.log("roster", f"Removed {c['name']} from the encounter")
    return mutate(eid, fn, _body().get("op_id"))


@bp.patch("/combatants/<int:cid>")
def api_patch_combatant(cid):
    eid = _enc_of_combatant(cid)
    changes = _body().get("changes")

    def fn(ctx):
        if not isinstance(changes, dict) or not changes:
            raise F.ApiError("No changes supplied")
        c = ctx.combatant(cid)
        for f in changes:
            if f not in F.COMBATANT:
                raise F.ApiError(f"Unknown field: {f}")
        if c["linked"]:
            char_changes = {k: v for k, v in changes.items() if k in LINKED_FIELDS or k == "name"}
            own = {k: v for k, v in changes.items() if k not in char_changes}
            if char_changes:
                F.cas_patch(ctx.conn, "characters", F.CHARACTER, c["character_id"], char_changes)
        else:
            if any(k in ("death_successes", "death_failures") for k in changes):
                raise F.ApiError("Death saves are tracked for characters only")
            own = changes
        updates = {}
        if own:
            spec = {k: v for k, v in F.COMBATANT.items() if k not in ("death_successes", "death_failures")}
            _, updates = F.cas_patch(ctx.conn, "combatants", spec, cid, own, touch=False)
        for k, change in changes.items():
            to = change.get("to")
            if k == "init_roll" and "init_roll" in updates:
                ctx.log("initiative", f"{c['name']}'s initiative set to {to if to not in (None, '') else '—'}")
            elif k == "status" and to != c["status"]:
                ctx.log("status", f"{c['name']} marked {to}")
            elif k == "ac" and str(to) != str(c["ac"]):
                ctx.log("edit", f"{c['name']}'s AC set to {to}")
            elif k == "name" and to != c["name"]:
                ctx.log("edit", f"{c['name']} renamed to {to}")
            elif k == "hidden" and bool(to) != c["hidden"]:
                ctx.log("edit", f"{c['name']} is now {'hidden from' if to else 'visible to'} players")
        if "init_roll" in updates and ctx.settings["auto_sort"]:
            _resort(ctx)
    return mutate(eid, fn, _body().get("op_id"))


# ---- initiative ------------------------------------------------------------

def _resort(ctx):
    order = ctx.combatants()
    tb = ctx.settings["tie_break"]
    order.sort(key=lambda c: initiative_sort_key(c, tb))
    for i, c in enumerate(order):
        ctx.conn.execute("UPDATE combatants SET sort_order = ? WHERE id = ?", (i, c["id"]))


@bp.post("/encounters/<int:eid>/roll")
def api_roll(eid):
    data = _body()
    scope = data.get("scope", "missing")

    def fn(ctx):
        rolled = []
        for c in ctx.combatants():
            if scope == "enemies" and c["kind"] != "enemy":
                continue
            if scope == "missing" and c["init_roll"] is not None:
                continue
            if scope == "ids" and c["id"] not in (data.get("ids") or []):
                continue
            d20 = roll_d20(rng)
            total = d20 + c["init_mod"]
            ctx.conn.execute("UPDATE combatants SET init_roll = ? WHERE id = ?", (total, c["id"]))
            rolled.append(f"{c['name']} {total} (d20 {d20} {'+' if c['init_mod'] >= 0 else '−'} {abs(c['init_mod'])})")
        if not rolled:
            raise F.ApiError("Nobody needed a roll")
        ctx.log("initiative", "Rolled initiative: " + "; ".join(rolled))
        _resort(ctx)
    return mutate(eid, fn, data.get("op_id"))


@bp.post("/encounters/<int:eid>/sort")
def api_sort(eid):
    def fn(ctx):
        _resort(ctx)
        ctx.log("initiative", "Turn order sorted by initiative")
    return mutate(eid, fn, _body().get("op_id"))


@bp.post("/encounters/<int:eid>/reorder")
def api_reorder(eid):
    data = _body()

    def fn(ctx):
        ids = [int(i) for i in data.get("ids") or []]
        current = [c["id"] for c in ctx.combatants()]
        if sorted(ids) != sorted(current):
            raise F.Conflict("The turn order changed elsewhere. The screen has been refreshed.")
        for i, cid in enumerate(ids):
            ctx.conn.execute("UPDATE combatants SET sort_order = ? WHERE id = ?", (i, cid))
        moved = data.get("moved_name")
        ctx.log("initiative", f"DM moved {moved} in the turn order" if moved else "DM changed the turn order")
    return mutate(eid, fn, data.get("op_id"))


# ---- HP -------------------------------------------------------------------------

def _vitals(c):
    return {k: c[k] for k in VITAL_KEYS}


def compute_hp(v, op, data, *, name, linked, max_hp, temp_stacking):
    """Apply one HP operation to a vitals dict (hp, max_hp, temp_hp, status,
    death saves). Pure: returns (new_vitals, label, note). Shared by the combat
    screen, rests and players updating their own character."""
    before = v
    v = dict(v)
    note = ""
    if op == "damage":
        amount = _int(data, "amount", 0, 99999)
        was = v["hp"]
        v["hp"], v["temp_hp"], absorbed, overflow = apply_damage(v["hp"], v["temp_hp"], amount)
        label = f"{name} takes {amount} damage"
        if absorbed:
            note = f" ({absorbed} absorbed by temp HP)"
        if was > 0 and v["hp"] == 0:
            if linked:
                if v["status"] == "ok":
                    v["status"] = "unconscious"
                note += " — drops to 0 HP and falls unconscious"
                if max_hp and overflow >= max_hp:
                    note += f"; {overflow} damage past 0 meets massive-damage rules (instant death) — DM's call"
            else:
                if v["status"] == "ok":
                    v["status"] = "defeated"
                note += " — defeated"
        elif was == 0 and amount > 0 and linked and v["status"] in ("unconscious", "stable"):
            note += " while at 0 HP — mark a failed death save (two on a crit)"
    elif op == "heal":
        amount = _int(data, "amount", 0, 99999)
        was = v["hp"]
        v["hp"] = apply_heal(v["hp"], v["max_hp"], amount)
        label = f"{name} heals {v['hp'] - was}" + (f" (of {amount})" if v["hp"] - was != amount else "")
        if was == 0 and v["hp"] > 0 and v["status"] in ("unconscious", "stable", "defeated"):
            v["status"] = "ok"
            v["death_successes"] = v["death_failures"] = 0
            note = " — back on their feet"
    elif op == "temp":
        amount = _int(data, "amount", 0, 99999)
        was = v["temp_hp"]
        v["temp_hp"] = apply_temp(v["temp_hp"], amount, temp_stacking)
        label = f"{name} gains temp HP: {was} → {v['temp_hp']}"
        if not temp_stacking and amount <= was:
            note = " (kept the higher value; temp HP doesn't stack)"
    elif op == "set":
        parts = []
        if "max_hp" in data:
            v["max_hp"] = _int(data, "max_hp", 0, 99999)
            parts.append(f"max {before['max_hp']} → {v['max_hp']}")
        if "hp" in data:
            v["hp"] = _int(data, "hp", 0, 99999)
            parts.append(f"HP {before['hp']} → {v['hp']}")
        if "temp_hp" in data:
            v["temp_hp"] = _int(data, "temp_hp", 0, 99999)
            parts.append(f"temp {before['temp_hp']} → {v['temp_hp']}")
        if not parts:
            raise F.ApiError("Nothing to set")
        if v["max_hp"] and v["hp"] > v["max_hp"]:
            v["hp"] = v["max_hp"]
        label = f"{name}: " + ", ".join(parts)
    else:
        raise F.ApiError("op must be damage, heal, temp or set")
    return v, label, note


def apply_hp(ctx, cid, data, by=None):
    """HP change on a combatant inside an encounter: logged, and recorded so
    the DM's Undo HP can reverse it. `by` names who did it (e.g. a player)."""
    c = ctx.combatant(cid)
    before = _vitals(c)
    v, label, note = compute_hp(before, data.get("op"), data, name=c["name"], linked=c["linked"],
                                max_hp=c["max_hp"], temp_stacking=ctx.settings["temp_hp_stacking"])
    if by:
        label = f"{label} ({by})"
    if v == before:
        ctx.log("hp", label + note + " (no change)")
        return v
    ctx.set_vitals(c, **v)
    hp_line = f" — {v['hp']}/{v['max_hp']} HP" + (f" +{v['temp_hp']} temp" if v["temp_hp"] else "")
    ctx.log("hp", label + note + hp_line)
    ctx.conn.execute(
        "INSERT INTO hp_changes (encounter_id, combatant_id, character_id, label, before, after, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (ctx.enc["id"], cid, c["character_id"] if c["linked"] else None, label, json.dumps(before), json.dumps(v), now_iso()))
    return v


@bp.post("/combatants/<int:cid>/hp")
def api_hp(cid):
    eid = _enc_of_combatant(cid)
    data = _body()
    return mutate(eid, lambda ctx: apply_hp(ctx, cid, data), data.get("op_id"))


@bp.post("/encounters/<int:eid>/damage")
def api_damage_targets(eid):
    """Deal damage to (or heal) one or more combatants at once: one attack, an area
    spell, or a healing ability. {targets: [combatant ids], amount, op: damage|heal,
    half: bool, attacker_id}. `half` is for targets that made their save; it rounds
    down. All targets change together or none do."""
    data = _body()
    op = data.get("op", "damage")
    if op not in ("damage", "heal"):
        raise F.ApiError("op must be damage or heal")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > 100 or not all(isinstance(t, int) and not isinstance(t, bool) for t in targets):
        raise F.ApiError("Choose who takes the damage")
    amount = data.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 or amount > 100000:
        raise F.ApiError("Damage must be a whole number, 0 or more")
    if data.get("half") and op == "damage":
        amount //= 2

    def fn(ctx):
        by = None
        if data.get("attacker_id") is not None:
            by = ("from " if op == "damage" else "by ") + ctx.combatant(int(data["attacker_id"]))["name"]
        for cid in dict.fromkeys(targets):
            apply_hp(ctx, cid, {"op": op, "amount": amount}, by)
    return mutate(eid, fn, data.get("op_id"))


@bp.post("/encounters/<int:eid>/undo")
def api_undo(eid):
    data = _body()

    def fn(ctx):
        ch = ctx.conn.execute(
            "SELECT * FROM hp_changes WHERE encounter_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1", (eid,)
        ).fetchone()
        if ch is None:
            raise F.ApiError("Nothing to undo")
        if ch["combatant_id"] is None:
            ctx.conn.execute("UPDATE hp_changes SET undone = 1 WHERE id = ?", (ch["id"],))
            raise F.ApiError("That combatant was removed; their change can't be undone")
        c = ctx.combatant(ch["combatant_id"])
        after, before = json.loads(ch["after"]), json.loads(ch["before"])
        if _vitals(c) != after and not data.get("force"):
            raise F.Conflict(
                f"{c['name']}'s HP changed again after “{ch['label']}”. Undoing would also discard that later change.",
                needs_force=True)
        ctx.set_vitals(c, **before)
        ctx.conn.execute("UPDATE hp_changes SET undone = 1 WHERE id = ?", (ch["id"],))
        ctx.log("hp", f"Undid: {ch['label']} — {before['hp']}/{before['max_hp']} HP")
    return mutate(eid, fn, data.get("op_id"))


# ---- conditions ----------------------------------------------------------------

@bp.post("/encounters/<int:eid>/conditions")
def api_condition_targets(eid):
    """Put one condition on several combatants at once (an effect spell like Fear or
    Hold Person). {targets, name, rounds, caster_id, note}. With a caster, the rounds
    count down at the start of the caster's turn, like a spell's duration. Anyone who
    already has it is skipped."""
    data = _body()
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > 100 or not all(isinstance(t, int) and not isinstance(t, bool) for t in targets):
        raise F.ApiError("Choose who it affects")
    name = str(data.get("name", "")).strip()[:60]
    if not name:
        raise F.ApiError("Name the condition or effect")

    def fn(ctx):
        rounds = _int(data, "rounds", 1, 1000) if data.get("rounds") not in (None, "") else None
        caster = ctx.combatant(int(data["caster_id"])) if data.get("caster_id") is not None else None
        added, skipped = [], []
        for cid in dict.fromkeys(targets):
            c = ctx.combatant(cid)
            if any(x["name"].lower() == name.lower() and not x.get("expired") for x in c["conditions"]):
                skipped.append(c["name"])
                continue
            tick_on = caster["id"] if caster else cid
            cond = {"id": uuid.uuid4().hex[:12], "name": name, "note": str(data.get("note", ""))[:500],
                    "rounds_left": rounds, "tick": "start" if caster else "end", "tick_on": tick_on, "encounter_id": eid,
                    "auto_expire": False, "expired": False, "applied_round": ctx.enc["round"]}
            ctx.set_vitals(c, conditions=c["conditions"] + [cond])
            added.append(c["name"])
        if added:
            rds = f" for {rounds} round{'s' if rounds != 1 else ''}" if rounds else ""
            ctx.log("condition", ", ".join(added) + (" is " if len(added) == 1 else " are ") + name + rds
                    + (f" ({caster['name']})" if caster else "") + (f" — {data['note']}" if data.get("note") else ""))
        if skipped:
            ctx.log("condition", ", ".join(skipped) + (" was" if len(skipped) == 1 else " were") + f" already {name}")
    return mutate(eid, fn, data.get("op_id"))


@bp.post("/combatants/<int:cid>/conditions")
def api_add_condition(cid):
    eid = _enc_of_combatant(cid)
    data = _body()

    def fn(ctx):
        c = ctx.combatant(cid)
        name = str(data.get("name", "")).strip()[:60]
        if not name:
            raise F.ApiError("Name the condition")
        rounds = data.get("rounds")
        rounds = _int(data, "rounds", 1, 1000) if rounds not in (None, "") else None
        tick = data.get("tick", "end")
        if tick not in ("start", "end"):
            raise F.ApiError("tick must be start or end")
        tick_on = _int(data, "tick_on", default=cid) if data.get("tick_on") else cid
        ctx.combatant(tick_on)
        cond = {"id": uuid.uuid4().hex[:12], "name": name, "note": str(data.get("note", ""))[:500],
                "rounds_left": rounds, "tick": tick, "tick_on": tick_on, "encounter_id": eid,
                "auto_expire": bool(data.get("auto_expire")), "expired": False, "applied_round": ctx.enc["round"]}
        if any(x["name"].lower() == name.lower() and not x.get("expired") for x in c["conditions"]):
            raise F.ApiError(f"{c['name']} is already {name}")
        ctx.set_vitals(c, conditions=c["conditions"] + [cond])
        desc = ""
        if rounds:
            whose = "their" if tick_on == cid else f"{ctx.combatant(tick_on)['name']}'s"
            desc = f" for {rounds} round{'s' if rounds != 1 else ''} (counts at the {tick} of {whose} turn)"
        ctx.log("condition", f"{c['name']} is {name}{desc}" + (f" — {cond['note']}" if cond["note"] else ""))
    return mutate(eid, fn, data.get("op_id"))


@bp.delete("/combatants/<int:cid>/conditions/<cond_id>")
def api_remove_condition(cid, cond_id):
    eid = _enc_of_combatant(cid)

    def fn(ctx):
        c = ctx.combatant(cid)
        match = [x for x in c["conditions"] if x.get("id") == cond_id]
        if not match:
            raise F.Conflict("That condition was already removed")
        ctx.set_vitals(c, conditions=[x for x in c["conditions"] if x.get("id") != cond_id])
        ctx.log("condition", f"{match[0]['name']} removed from {c['name']}")
    return mutate(eid, fn, _body().get("op_id"))


@bp.patch("/combatants/<int:cid>/conditions/<cond_id>")
def api_update_condition(cid, cond_id):
    eid = _enc_of_combatant(cid)
    data = _body()

    def fn(ctx):
        c = ctx.combatant(cid)
        conds = c["conditions"]
        target = next((x for x in conds if x.get("id") == cond_id), None)
        if target is None:
            raise F.Conflict("That condition was removed")
        if "rounds_left" in data:
            r = data["rounds_left"]
            target["rounds_left"] = _int(data, "rounds_left", 0, 1000) if r not in (None, "") else None
            target["expired"] = False
            ctx.log("condition", f"{target['name']} on {c['name']}: "
                    + (f"{target['rounds_left']} round(s) left" if target["rounds_left"] is not None else "no fixed duration"))
        if "note" in data:
            target["note"] = str(data["note"])[:500]
        ctx.set_vitals(c, conditions=conds)
    return mutate(eid, fn, data.get("op_id"))


# ---- log --------------------------------------------------------------------

@bp.post("/encounters/<int:eid>/log")
def api_note(eid):
    data = _body()

    def fn(ctx):
        msg = str(data.get("message", "")).strip()
        if not msg:
            raise F.ApiError("Write a note first")
        ctx.log("note", msg[:2000])
    return mutate(eid, fn, data.get("op_id"))


@bp.get("/encounters/<int:eid>/log")
def api_full_log(eid):
    rows = get_db().execute("SELECT * FROM combat_log WHERE encounter_id = ? ORDER BY id", (eid,)).fetchall()
    return jsonify({"log": [dict(r) for r in rows]})
