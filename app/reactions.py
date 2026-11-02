"""Reactions: everyone in a fight has one each round. It comes back at the start of their own
turn, and it's spent by a move they make off their turn:

    parry     Yamato's Parry (a d20 roll-off; win and the hit does half)        when they're hit
    deflect   Moni's Deflect Attacks: the hit is cut by dice (1d10 + Dex + level);
              brought down to 0, she can send it at an enemy near her            when they're hit
    absorb    Moni's Absorb Elements: her next hit does extra dice of that type  when they're hit
    sentinel  Gnocchi's Sentinel: an enemy next to her attacks someone else, and
              she makes a melee attack against it                              when that happens

A sheet row (spell or attack) is a reaction when its "reaction" field names one of these (or,
for rows from before, when Parry is ticked). The state of a combatant's reaction is kept on
the combatant (column `reaction`, JSON):

    used   {"what", "round"}                 spent this round (cleared at the start of their turn)
    hit    {"change", "amount", "by", "name", "type", "ranged", "round", "turn"}   the last hit on them
    offer  {"kind": "sentinel" | "redirect", ...}   something they can do right now with it

Players and the DM both see the offers (players only their own), and anyone can "burn" a
reaction by hand for a reaction the app doesn't know (an opportunity attack, a monster's Parry).
"""
import json
import re
import uuid

from . import fields as F
from .db import now_iso

KINDS = ("parry", "deflect", "absorb", "sentinel")
ELEMENTS = ("acid", "cold", "fire", "lightning", "thunder")
NAMES = {"parry": "Parry", "deflect": "Deflect Attacks", "absorb": "Absorb Elements", "sentinel": "Sentinel"}
MARK = {"parry": "(parried)", "deflect": "(deflected)", "absorb": "(absorbed)"}
REDIRECT_MELEE, REDIRECT_RANGED = 10, 60


# ---- what's on the sheet ----------------------------------------------------------------

def row_kind(r):
    """The reaction a sheet row is, or ''."""
    if not isinstance(r, dict):
        return ""
    k = str(r.get("reaction") or "").strip().lower()
    if k in KINDS:
        return k
    return "parry" if r.get("parry") else ""


def rows_of(ch):
    """[{kind, name, where, index, cooldown, reduce, redirect, bonus, attack}] for a character
    (decoded), spells first, then attacks."""
    from .rules import parse_cooldown, spell_info
    out = []
    for where in ("spells", "attacks"):
        for i, r in enumerate(ch.get(where) or []):
            k = row_kind(r)
            if not k:
                continue
            name = (str(r.get("name") or "").strip() or NAMES[k])[:80]
            out.append({"kind": k, "name": name, "where": where, "index": i,
                        "cooldown": spell_info(r)["cooldown"] if where == "spells" else parse_cooldown(r),
                        "reduce": str(r.get("reduce") or ("1d10+dex+level" if k == "deflect" else "")).strip()[:40],
                        "redirect": bool(r.get("redirect", k == "deflect")),
                        "bonus": str(r.get("bonus_dice") or ("1d12" if k == "absorb" else "")).strip()[:20],
                        "attack": r.get("attack_row"),
                        # it has to be cast first, on their turn (Moni's Absorb Elements); then a hit can set it off
                        "prime": bool(r.get("prime"))})
    return out


def _char(conn, char_id):
    row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    return F.decode_row(row, F.CHARACTER) if row else None


TOKEN = re.compile(r"\b(str|dex|con|int|wis|cha|level|lvl|prof)\b", re.I)


def resolve_dice(text, ch):
    """'1d10+dex+level' -> '1d10+1+5' for this character (their Dex modifier, level, proficiency)."""
    from .rules import derived
    d = derived(ch)

    def sub(m):
        w = m.group(1).lower()
        if w in ("level", "lvl"):
            return str(int(ch.get("level") or 1))
        if w == "prof":
            return str(d["prof"])
        return str(d["mods"][w])
    out = TOKEN.sub(sub, str(text or "")).replace(" ", "")
    return re.sub(r"\+-", "-", re.sub(r"--", "+", out)).lstrip("+") or "0"


# ---- the state on the combatant ----------------------------------------------------------

def load(conn, cb_id):
    row = conn.execute("SELECT reaction FROM combatants WHERE id = ?", (cb_id,)).fetchone()
    try:
        st = json.loads(row["reaction"] or "{}") if row else {}
    except (ValueError, TypeError):
        st = {}
    return st if isinstance(st, dict) else {}


def save(conn, cb_id, st):
    conn.execute("UPDATE combatants SET reaction = ? WHERE id = ?", (json.dumps(st), cb_id))


def reset(conn, cb_id):
    """The start of their own turn: the reaction is back, and old offers are gone."""
    st = load(conn, cb_id)
    if st.get("used") or st.get("offer"):
        st.pop("used", None)
        st.pop("offer", None)
        save(conn, cb_id, st)


def reset_all(conn, eid):
    conn.execute("UPDATE combatants SET reaction = '{}' WHERE encounter_id = ?", (eid,))


def _now(ctx):
    return {"round": ctx.enc["round"], "turn": ctx.enc["current_id"]}


def _fresh(ctx, rec):
    """Did this happen during the turn that's going on now?"""
    return bool(rec) and rec.get("round") == ctx.enc["round"] and rec.get("turn") == ctx.enc["current_id"]


def ready(conn, cb_id):
    return not load(conn, cb_id).get("used")


def spend(ctx, cid, what, quiet=False):
    """Use their reaction for `what`. Refused when it's already been used this round."""
    c = ctx.combatant(cid)
    st = load(ctx.conn, cid)
    if st.get("used"):
        raise F.ApiError(f"{c['name']} has already used their reaction this round ({st['used'].get('what') or 'used'}) — "
                         "it comes back at the start of their turn", status=409)
    if ctx.enc["status"] != "active":
        raise F.ApiError("Reactions are for a running fight")
    st["used"] = {"what": str(what)[:80], "round": ctx.enc["round"]}
    st.pop("offer", None)
    save(ctx.conn, cid, st)
    if not quiet:
        ctx.log("action", f"{c['name']} uses their reaction: {what}")


def give_back(ctx, cid):
    """The DM gives a reaction back (a misclick)."""
    c = ctx.combatant(cid)
    st = load(ctx.conn, cid)
    if not st.get("used"):
        raise F.ApiError(f"{c['name']} still has their reaction")
    st.pop("used", None)
    save(ctx.conn, cid, st)
    ctx.log("action", f"The DM gave {c['name']} their reaction back")


# ---- what happened: hits and attacks ------------------------------------------------------

def note_hit(ctx, cid, change_id, amount):
    """apply_hp dealt damage to someone: remember the hit (who, with what) so a reaction to it
    knows. ctx.attack (set by whoever made the attack) says who and how."""
    a = getattr(ctx, "attack", None) or {}
    st = load(ctx.conn, cid)
    st["hit"] = {"change": change_id, "amount": int(amount), "by": a.get("by"), "name": str(a.get("name") or "")[:60],
                 "type": str(a.get("type") or "")[:20], "ranged": a.get("ranged"), **_now(ctx)}
    save(ctx.conn, cid, st)


def note_attack(ctx, attacker_id, target_ids):
    """Someone made an attack (hit or miss) at these targets: anyone with Sentinel standing next
    to the attacker, who wasn't the one attacked, may hit it back with their reaction."""
    from .movement import distance_ft
    if ctx.enc["status"] != "active" or attacker_id is None:
        return
    try:
        att = ctx.combatant(int(attacker_id))
    except (F.NotFound, TypeError, ValueError):
        return
    targets = {int(t) for t in target_ids or []}
    if att["hidden"] or att["status"] in ("dead", "defeated", "fled"):
        return
    for c in ctx.combatants():
        if not c["linked"] or c["id"] in targets or c["id"] == att["id"] or (c["kind"] == "enemy") == (att["kind"] == "enemy"):
            continue
        if c["hp"] <= 0 or c["status"] not in ("ok",):
            continue
        ch = _char(ctx.conn, c["character_id"])
        row = next((r for r in rows_of(ch) if r["kind"] == "sentinel"), None) if ch else None
        if row is None:
            continue
        d = distance_ft(ctx.conn, ctx.enc["id"], c["id"], att["id"])
        if d is not None and d > 5:
            continue
        st = load(ctx.conn, c["id"])
        if st.get("used"):
            continue
        st["offer"] = {"kind": "sentinel", "name": row["name"], "vs": att["id"], "vs_name": att["name"],
                       "on": [ctx.combatant(t)["name"] for t in targets if _exists(ctx, t)][:3], "far": d, **_now(ctx)}
        save(ctx.conn, c["id"], st)


def _exists(ctx, cid):
    try:
        ctx.combatant(cid)
        return True
    except F.NotFound:
        return False


def pending_hit(ctx, c, st=None):
    """The hit just taken that a reaction can still answer: {change, amount, by, name, type, ranged},
    or None. It has to be the last thing that changed their HP, during this same turn."""
    from .combat import VITAL_KEYS
    st = st if st is not None else load(ctx.conn, c["id"])
    hit = ctx.conn.execute("SELECT * FROM hp_changes WHERE encounter_id = ? AND combatant_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1",
                           (ctx.enc["id"], c["id"])).fetchone()
    if hit is None or any(hit["label"].endswith(m) for m in MARK.values()):
        return None
    before, after = json.loads(hit["before"]), json.loads(hit["after"])
    m = re.search(r"takes (\d+) damage", hit["label"])
    now = {k: c[k] for k in VITAL_KEYS}
    if not m or before["hp"] + before["temp_hp"] <= after["hp"] + after["temp_hp"] or now != after:
        return None
    rec = st.get("hit") or {}
    if rec.get("change") == hit["id"] and not _fresh(ctx, rec):
        return None  # an older turn's hit: too late to react to it
    info = rec if rec.get("change") == hit["id"] else {}
    return {"change": hit["id"], "amount": int(m.group(1)), "by": info.get("by"), "name": info.get("name") or "",
            "type": info.get("type") or "", "ranged": info.get("ranged")}


def _ranged(ctx, c, hit):
    """Was the hit from range (a bow, a bolt) rather than up close? Told by the attack, or else by
    how far away the attacker stands (more than 10 ft: ranged)."""
    if hit.get("ranged") is not None:
        return bool(hit["ranged"])
    from .movement import distance_ft
    from .rules import RANGED_WORDS
    if RANGED_WORDS.search(hit.get("name") or ""):
        return True
    if hit.get("by"):
        d = distance_ft(ctx.conn, ctx.enc["id"], c["id"], hit["by"])
        return d is not None and d > 10
    return False


def info(ctx, c, ch=None):
    """What a combatant's reaction looks like right now, for the screens:
    {ready, used, rows: [names], offers: [{kind, name, ...}]}."""
    st = load(ctx.conn, c["id"])
    out = {"ready": not st.get("used"), "used": (st.get("used") or {}).get("what"), "rows": [], "offers": []}
    if ctx.enc["status"] != "active":
        return out
    rows = rows_of(ch) if ch else []
    out["rows"] = [{"kind": r["kind"], "name": r["name"]} for r in rows]
    # reactions that need casting first: the ones not cast yet (a button on their turn), and the cast ones
    out["prime"] = [{"kind": r["kind"], "name": r["name"], "bonus": r["bonus"]} for r in rows if r["prime"] and not primed(c, r["name"])]
    out["primed"] = [r["name"] for r in rows if r["prime"] and primed(c, r["name"])]
    offer = st.get("offer") or {}
    if offer.get("kind") == "redirect" and _fresh(ctx, offer):  # part of a Deflect that's already used
        out["offers"].append(dict(offer, targets=_redirect_targets(ctx, c, offer)))
    if st.get("used") or c["status"] in ("dead",):
        return out
    from .rules import cooldown_left
    hit = pending_hit(ctx, c, st) if any(r["kind"] in ("deflect", "absorb") for r in rows) else None
    for r in rows:
        if cooldown_left(c["conditions"], r["name"], ctx.enc["id"]):
            continue
        if r["kind"] == "deflect" and hit:
            out["offers"].append({"kind": "deflect", "name": r["name"], "amount": hit["amount"], "reduce": resolve_dice(r["reduce"], ch),
                                  "redirect": r["redirect"], "by_name": _name(ctx, hit.get("by"))})
        elif r["kind"] == "absorb" and hit and (not hit["type"] or hit["type"] in ELEMENTS) and (not r["prime"] or primed(c, r["name"])):
            out["offers"].append({"kind": "absorb", "name": r["name"], "amount": hit["amount"], "type": hit["type"], "bonus": r["bonus"]})
        elif r["kind"] == "sentinel" and offer.get("kind") == "sentinel" and _fresh(ctx, offer) and _standing(ctx, offer.get("vs")):
            out["offers"].append({"kind": "sentinel", "name": r["name"], "vs": offer["vs"], "vs_name": offer.get("vs_name"),
                                  "on": offer.get("on") or [], "attack": _hit_back_row(ch, r)[1] if ch else ""})
    return out


def primed(c, name):
    """The effect a cast-first reaction leaves on them until a hit sets it off, or None."""
    return next((x for x in c["conditions"] if isinstance(x, dict) and x.get("primed") == name and not x.get("expired")), None)


def prime(ctx, cid, name=None):
    """Cast a reaction that has to be ready before the hit (Absorb Elements): on their own turn,
    as one of their actions. It waits on them (until a hit sets it off, or the fight ends)."""
    from .combat import used_a_move
    from .maps import attack_fx
    from .movement import check_action
    c = ctx.combatant(cid)
    ch = _char(ctx.conn, c["character_id"]) if c["linked"] else None
    rows = [r for r in rows_of(ch) if r["prime"] and (not name or r["name"] == str(name).strip())] if ch else []
    if not rows:
        raise F.ApiError(f"{c['name']} has nothing to cast ahead like that")
    row = rows[0]
    if ctx.enc["status"] != "active":
        raise F.ApiError("That's for a running fight")
    if ctx.enc["current_id"] != cid:
        raise F.ApiError(f"Cast {row['name']} on {c['name']}'s turn", status=403)
    if primed(c, row["name"]):
        raise F.ApiError(f"{row['name']} is already cast — it's waiting for a hit")
    check_action(ctx.conn, cid, row["name"])
    cond = {"id": uuid.uuid4().hex[:12], "name": row["name"] + " (cast)", "primed": row["name"],
            "note": f"When you're hit, use your reaction: +{row['bonus'] or '1d12'} on your next hit", "rounds_left": None,
            "encounter_id": ctx.enc["id"], "expired": False, "applied_round": ctx.enc["round"]}
    ctx.set_vitals(c, conditions=c["conditions"] + [cond])
    ctx.log("spell", f"{c['name']} casts {row['name']}: ready for the next hit (a reaction)")
    used_a_move(ctx, cid, row["name"])
    attack_fx(ctx.conn, ctx.enc["id"], cid, [(cid, "auto")], row["name"], "buff", "", None, "arcane")
    return {"kind": "prime", "name": row["name"], "text": f"{row['name']} is cast — when you're hit, you can use it."}


def _name(ctx, cid):
    """A combatant's name (blank for one hidden from the players)."""
    if not cid:
        return ""
    try:
        x = ctx.combatant(int(cid))
    except (F.NotFound, TypeError, ValueError):
        return ""
    return "" if x["hidden"] else x["name"]


def _standing(ctx, cid):
    try:
        x = ctx.combatant(int(cid))
    except (F.NotFound, TypeError, ValueError):
        return False
    return x["status"] not in ("dead", "defeated", "fled") and x["hp"] > 0


def _redirect_targets(ctx, c, offer):
    """The enemies Moni can send the deflected attack at: within 10 ft (a melee hit) or 60 ft
    (a projectile) of her. Without a battle map, every enemy still standing."""
    from .movement import distance_ft
    out = []
    for x in ctx.combatants():
        if (x["kind"] == "enemy") == (c["kind"] == "enemy") or x["hidden"] or not _standing(ctx, x["id"]):
            continue
        d = distance_ft(ctx.conn, ctx.enc["id"], c["id"], x["id"])
        if d is None or d <= offer.get("range", REDIRECT_MELEE):
            out.append({"id": x["id"], "name": x["name"], "ft": d})
    return out


def _hit_back_row(ch, r):
    """The attack Sentinel hits back with: the one its row names, else the first melee attack
    with damage on the sheet. Returns (row, name) or (None, '')."""
    from . import dice
    from .rules import melee_reach
    rows = ch.get("attacks") or []
    pick = r.get("attack")
    if isinstance(pick, int) and 0 <= pick < len(rows) and dice.damage_expression(str(rows[pick].get("damage") or "")):
        return rows[pick], (rows[pick].get("name") or "Attack").strip()
    for a in rows:
        if isinstance(a, dict) and dice.damage_expression(str(a.get("damage") or "")) and melee_reach(a) and not re.search(r"\bheal", str(a.get("notes") or "") + str(a.get("name") or ""), re.I):
            return a, (a.get("name") or "Attack").strip()
    return None, ""


# ---- using it ------------------------------------------------------------------------------

def _redo_hit(ctx, c, change_id, taken, marker, label):
    """Put the hit back as if it did `taken` damage instead (the HP from just before it)."""
    from .combat import compute_hp
    hit = ctx.conn.execute("SELECT * FROM hp_changes WHERE id = ?", (change_id,)).fetchone()
    before, after = json.loads(hit["before"]), json.loads(hit["after"])
    v, _l, _n = compute_hp(before, "damage", {"amount": taken}, name=c["name"], linked=c["linked"], max_hp=before["max_hp"],
                           temp_stacking=ctx.settings["temp_hp_stacking"])
    if after["hp"] == 0 and v["hp"] > 0:
        v["status"] = before["status"]
        c2 = ctx.combatant(c["id"])
        ctx.set_vitals(c2, conditions=[x for x in c2["conditions"] if not (x.get("name") == "Prone" and x.get("note") == "Knocked down at 0 HP")])
    ctx.set_vitals(ctx.combatant(c["id"]), **v)
    ctx.conn.execute("UPDATE hp_changes SET label = label || ? WHERE id = ?", (" " + marker, change_id))
    ctx.conn.execute("INSERT INTO hp_changes (encounter_id, combatant_id, character_id, label, before, after, created_at) VALUES (?,?,?,?,?,?,?)",
                     (ctx.enc["id"], c["id"], c["character_id"] if c["linked"] else None, label + " " + marker, json.dumps(after), json.dumps(v), now_iso()))
    return v


def react(ctx, cid, kind, data=None, viewer=None):
    """Use a reaction. kind: deflect | absorb | sentinel | redirect | burn. Returns what happened."""
    from .maps import attack_fx
    from .rolls import save_roll
    from . import dice
    data = data or {}
    c = ctx.combatant(cid)
    if ctx.enc["status"] != "active":
        raise F.ApiError("Reactions are for a running fight")
    if kind == "burn":
        what = str(data.get("what") or "a reaction").strip()[:60] or "a reaction"
        spend(ctx, cid, what)
        return {"kind": "burn", "text": f"{c['name']} used their reaction ({what})."}
    if kind == "redirect":
        return _redirect(ctx, c, data)
    if kind == "prime":
        return prime(ctx, cid, data.get("name"))
    ch = _char(ctx.conn, c["character_id"]) if c["linked"] else None
    if ch is None:
        raise F.ApiError("That reaction is on a character's sheet")
    row = next((r for r in rows_of(ch) if r["kind"] == kind), None)
    if row is None:
        raise F.ApiError(f"{c['name']} has no {NAMES.get(kind, kind)} on their sheet")
    from .rules import cooldown_left
    left = cooldown_left(c["conditions"], row["name"], ctx.enc["id"])
    if left:
        raise F.ApiError(f"{row['name']} is recharging")
    st = load(ctx.conn, cid)
    if st.get("used"):
        raise F.ApiError(f"{c['name']} has already used their reaction this round — it comes back at the start of their turn", status=409)
    viewer = viewer or ctx.viewer or {"role": "dm", "name": "DM"}
    ids = {"encounter_id": ctx.enc["id"], "combatant_id": cid, "character_id": c["character_id"]}
    out = {"kind": kind, "name": row["name"]}
    if kind in ("deflect", "absorb"):
        hit = pending_hit(ctx, c, st)
        if hit is None:
            raise F.ApiError(f"There's no hit on {c['name']} to answer right now")
        if kind == "deflect":
            expr = resolve_dice(row["reduce"], ch)
            try:
                r = dice.roll(expr)
            except dice.DiceError as e:
                raise F.ApiError(f"{row['name']}: {e}")
            cut = max(0, r["total"])
            taken = max(0, hit["amount"] - cut)
            spend(ctx, cid, row["name"], quiet=True)
            save_roll(ctx.conn, viewer, ctx.enc["campaign_id"], dict(r, applied=True), label=f"{row['name']} — damage cut", kind="custom",
                      subject=c["name"], ids=ids, outcome=f"Cuts {cut}: takes {taken} instead of {hit['amount']}")
            v = _redo_hit(ctx, c, hit["change"], taken, MARK["deflect"], f"{c['name']} deflects: takes {taken} instead of {hit['amount']}")
            ctx.log("hp", f"{c['name']} uses {row['name']} (reaction): {expr} = {cut}, takes {taken} instead of {hit['amount']} — {v['hp']}/{v['max_hp']} HP")
            out.update(cut=cut, amount=hit["amount"], taken=taken, expr=expr)
            attack_fx(ctx.conn, ctx.enc["id"], cid, [(cid, "saved")], row["name"], "buff", "", None, "holy")
            if taken == 0 and row["redirect"]:
                ranged = _ranged(ctx, c, hit)
                offer = {"kind": "redirect", "name": row["name"], "amount": hit["amount"], "range": REDIRECT_RANGED if ranged else REDIRECT_MELEE,
                         "ranged": ranged, "type": hit["type"], **_now(ctx)}
                st = load(ctx.conn, cid)
                st["offer"] = offer
                save(ctx.conn, cid, st)
                out["redirect"] = dict(offer, targets=_redirect_targets(ctx, c, offer))
        else:
            typ = hit["type"]
            if typ and typ not in ELEMENTS:
                raise F.ApiError(f"{row['name']} works on acid, cold, fire, lightning or thunder damage — that hit was {typ}")
            spend(ctx, cid, row["name"], quiet=True)
            mine = ctx.enc["current_id"] == cid
            bonus = row["bonus"] or "1d12"
            cond = {"id": uuid.uuid4().hex[:12], "name": row["name"], "note": f"+{bonus}{' ' + typ if typ else ''} damage on your next hit",
                    "dmg_mod": "+" + bonus.lstrip("+"), "once": True, "rounds_left": 2 if mine else 1, "tick": "end", "tick_on": cid,
                    "encounter_id": ctx.enc["id"], "auto_expire": True, "expired": False, "applied_round": ctx.enc["round"],
                    "source": {"spell": row["name"], "caster": cid}}
            if row["prime"] and not primed(c, row["name"]):
                raise F.ApiError(f"{row['name']} has to be cast first, on {c['name']}'s turn")
            c2 = ctx.combatant(cid)
            ctx.set_vitals(c2, conditions=[x for x in c2["conditions"] if (x.get("name") != row["name"] or x.get("cooldown"))
                                           and x.get("primed") != row["name"]] + [cond])
            ctx.conn.execute("UPDATE hp_changes SET label = label || ? WHERE id = ?", (" " + MARK["absorb"], hit["change"]))
            ctx.log("condition", f"{c['name']} uses {row['name']} (reaction): +{bonus}{' ' + typ if typ else ''} damage on their next hit")
            out.update(bonus=bonus, type=typ)
            attack_fx(ctx.conn, ctx.enc["id"], cid, [(cid, "auto")], row["name"], "buff", typ, None,
                      {"fire": "flames", "cold": "frost", "lightning": "sparks", "thunder": "sparks", "acid": "venom"}.get(typ, "arcane"))
    elif kind == "sentinel":
        offer = st.get("offer") or {}
        if offer.get("kind") != "sentinel" or not _fresh(ctx, offer) or not _standing(ctx, offer.get("vs")):
            raise F.ApiError("No enemy next to you has attacked someone else just now")
        atk, atk_name = _hit_back_row(ch, row)
        if atk is None:
            raise F.ApiError(f"{c['name']} has no melee attack with damage on their sheet to hit back with")
        from .play import _attack_spec
        from .spells import cast
        spec = dict(_attack_spec(atk, ch), cooldown=0)
        spend(ctx, cid, f"{row['name']} — {atk_name} on {offer.get('vs_name')}", quiet=True)
        ctx.log("action", f"{row['name']}! {c['name']} uses their reaction to strike {offer.get('vs_name')}")
        res = cast(ctx, cid, {"spell": spec, "targets": [int(offer["vs"])], "force": True}, viewer)
        out.update(vs=offer["vs"], vs_name=offer.get("vs_name"), attack=atk_name, summary=res["summary"], targets=res["targets"],
                   rolls=res["rolls"])
    else:
        raise F.ApiError("Parry has its own button")
    if row["cooldown"]:
        from .combat import start_cooldown
        start_cooldown(ctx, cid, row["name"], row["cooldown"])
    return out


def _redirect(ctx, c, data):
    """The second half of a Deflect that brought the hit to 0: the attack goes at an enemy
    within reach instead, for the damage it would have done."""
    from .combat import apply_hp
    from .maps import attack_fx
    st = load(ctx.conn, c["id"])
    offer = st.get("offer") or {}
    if offer.get("kind") != "redirect" or not _fresh(ctx, offer):
        raise F.ApiError("There's no deflected attack to send back right now")
    try:
        tid = int(data.get("target"))
    except (TypeError, ValueError):
        raise F.ApiError("Pick who the attack goes to")
    ok = {x["id"]: x for x in _redirect_targets(ctx, c, offer)}
    if tid not in ok:
        raise F.ApiError(f"They're not an enemy within {offer.get('range', REDIRECT_MELEE)} ft of {c['name']}")
    st.pop("offer", None)
    save(ctx.conn, c["id"], st)
    ctx.attack = {"by": c["id"], "name": offer.get("name"), "type": offer.get("type"), "ranged": offer.get("ranged")}
    v = apply_hp(ctx, tid, {"op": "damage", "amount": int(offer["amount"])}, f"{offer.get('name')}, {c['name']}")
    ctx.attack = None
    ctx.log("hp", f"{c['name']} sends the attack back at {ok[tid]['name']}: {offer['amount']} damage")
    attack_fx(ctx.conn, ctx.enc["id"], c["id"], [(tid, "hit")], offer.get("name") or "Redirect", "damage", offer.get("type") or "", None,
              "arrow" if offer.get("ranged") else "punch")
    return {"kind": "redirect", "name": offer.get("name"), "target": ok[tid]["name"], "amount": int(offer["amount"]), "hp": v.get("hp")}


# ---- Phantasmal Killers: a clone that's destroyed bursts -----------------------------------

def death_burst(ctx, c):
    """A summoned clone with on_death (Yamato's Phantasmal Killers) was just destroyed: every
    enemy of its summoner within reach of it makes the save (Dex DC 10) or loses one action on
    its next turn. Without a battle map nobody can be told to be in it, so the log says so."""
    from .maps import attack_fx
    from .movement import distance_ft
    from .spells import Roller, roll_save
    burst = (c.get("statblock") or {}).get("on_death") or {}
    if not burst or (c.get("statblock") or {}).get("burst_done"):
        return
    sb = dict(c["statblock"], burst_done=True)
    ctx.conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), c["id"]))
    reach, ability, dc = int(burst.get("reach") or 5), burst.get("save") or "dex", int(burst.get("dc") or 10)
    roller, lines, hows, any_map = Roller(ctx), [], [], False
    for t in ctx.combatants():
        if t["id"] == c["id"] or (t["kind"] == "enemy") == (c["kind"] == "enemy") or not _standing(ctx, t["id"]):
            continue
        d = distance_ft(ctx.conn, ctx.enc["id"], c["id"], t["id"])
        if d is None:
            continue
        any_map = True
        if d > reach:
            continue
        made, _total, how = roll_save(roller, t, ability, dc, f"{c['name']} bursts")
        hows.append((t["id"], "saved" if made else "failed"))
        if made:
            lines.append(f"{t['name']} saves ({how})")
            continue
        now = ctx.enc["current_id"] == t["id"]
        cond = {"id": uuid.uuid4().hex[:12], "name": "Shaken", "note": f"Loses one action on its next turn ({c['name']} burst)",
                "lose_actions": 1, "skip_turn": f"{ctx.enc['round']}:{t['id']}" if now else "",
                "rounds_left": 2 if now else 1, "tick": "end", "tick_on": t["id"], "encounter_id": ctx.enc["id"], "auto_expire": True,
                "expired": False, "applied_round": ctx.enc["round"], "source": {"spell": burst.get("name") or "Phantasmal Killers"}}
        tt = ctx.combatant(t["id"])
        ctx.set_vitals(tt, conditions=tt["conditions"] + [cond])
        lines.append(f"{t['name']} fails ({how}) and loses an action on its next turn")
    if lines:
        ctx.log("spell", f"{c['name']} bursts as it's destroyed: " + "; ".join(lines))
    elif not any_map:
        ctx.log("spell", f"{c['name']} bursts as it's destroyed — enemies within {reach} ft make a {ability.capitalize()} save DC {dc} "
                "or lose an action on their next turn (no battle map to tell who's close)")
    else:
        ctx.log("spell", f"{c['name']} bursts as it's destroyed — nobody was within {reach} ft")
    attack_fx(ctx.conn, ctx.enc["id"], c["id"], hows or [(c["id"], "auto")], burst.get("name") or "Phantasmal burst", "damage", "psychic",
              {"kind": "circle", "size": max(5, reach)}, "arcane")
