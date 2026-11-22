"""Enemies that take their own turn ("Let it act" on the DM's map and Combat screen, or on their own
with the campaign setting "Enemies act on their own").

On its turn an enemy on a battle map:
  1. recovers (regeneration) and re-rolls its spent Recharge 5–6 moves,
  2. picks a target by its tactics (nearest, the weakest, or the one farthest from its friends),
  3. moves along a real path (round walls and machines; fliers over pits), within its speed, to where
     it can hit: next to the target for a brawler, at range with a clear shot for a shooter, backing off
     from melee if it's a drone or the warden; it dashes when it can't reach anyone this turn,
  4. attacks with its stat block's lines: Multiattack's count, to-hit against AC, damage dice (doubled
     on a 20), saves for areas (half on a save) and conditions (Stunned, Prone, Restrained...).
Every roll is a normal roll (the dice tumble for everyone), every hit goes through the usual damage
code (reactions, concentration, Death Ward, drops), everything shows on the map, and "Undo last
action" takes the whole turn back.

Prison enemies have their own tactics (app/prison_monsters.py TACTICS); any other monster fights as
a brawler or a shooter, from its attack lines.
"""
import json
import math
import random
import re
from collections import deque

from flask import Blueprint, jsonify, request

from . import dice
from . import fields as F
from .db import now_iso, tx

bp = Blueprint("ai", __name__, url_prefix="/api")

NUM = {"one": 1, "two": 2, "three": 3, "four": 4}
ABIL = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
CONDS = ("Stunned", "Prone", "Restrained", "Frightened", "Poisoned", "Blinded", "Grappled", "Paralyzed", "Incapacitated")
CANT_ACT = {"stunned", "paralyzed", "incapacitated", "unconscious", "petrified"}


# ---- reading the stat block ------------------------------------------------------------------------

def parse_moves(text):
    """(multiattack count, [moves]) from attack lines."""
    multi, moves = 1, []
    for raw in str(text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\s*([^.:]{1,60})[.:]", line)
        name = re.sub(r"\s*\(recharge[^)]*\)", "", (m.group(1) if m else line[:30]), flags=re.I).strip()
        if name.lower() == "multiattack":
            w = re.search(r"\b(one|two|three|four|\d)\b", line, re.I)
            multi = NUM.get(w.group(1).lower(), int(w.group(1)) if w and w.group(1).isdigit() else 2) if w else 2
            continue
        hit = re.search(r"([+-]\s*\d+)\s*to hit", line, re.I)
        dmg = re.search(r"\((\d+d\d+(?:\s*[+-]\s*\d+)?)\)", line) or re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", line)
        save = re.search(r"DC\s*(\d+)\s*(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)", line, re.I)
        area = re.search(r"(\d+)\s*-?\s*(?:ft|foot|feet)\.?\s*(cone|line|radius|sphere|cube|square)", line, re.I)
        reach = re.search(r"reach\s*(\d+)", line, re.I)
        rng = re.search(r"range\s*(\d+)(?:\s*/\s*(\d+))?", line, re.I)
        within = re.search(r"within\s*(\d+)\s*(?:ft|feet)", line, re.I)
        rech = re.search(r"recharge\s*(\d)", line, re.I)
        dtype = re.search(r"\)\s*([a-z]+)\s+damage", line, re.I)
        look = re.search(r"\blook\s+([a-z]+)", line, re.I)
        cond = next((c for c in CONDS if re.search(r"\b" + c + r"\b", line, re.I)), None)
        rounds = re.search(r"\b" + cond + r"\s+(\d+)\s+rounds?", line, re.I) if cond else None
        if not (hit or (save and dmg)):
            continue
        mv = {"name": name, "line": line, "bonus": int(hit.group(1).replace(" ", "")) if hit else None,
              "dmg": dmg.group(1).replace(" ", "") if dmg else None, "type": dtype.group(1).lower() if dtype else "",
              "look": look.group(1).lower() if look else "", "recharge": int(rech.group(1)) if rech else 0,
              "cond": cond, "rounds": int(rounds.group(1)) if rounds else (1 if cond and cond != "Prone" else None),
              "save": (int(save.group(1)), ABIL[save.group(2).lower()]) if save else None}
        if area and not hit:
            k = area.group(2).lower()
            mv.update(kind="area", shape={"radius": "circle", "sphere": "circle", "cube": "square"}.get(k, k), size=int(area.group(1)),
                      range=int(within.group(1)) if within else 0)
        elif reach and not rng:
            mv.update(kind="melee", reach=int(reach.group(1)))
        elif rng:
            mv.update(kind="ranged", range=int(rng.group(1)), long=int(rng.group(2) or rng.group(1)), reach=int(reach.group(1)) if reach else 0)
        elif reach or re.search(r"melee", line, re.I):
            mv.update(kind="melee", reach=int(reach.group(1)) if reach else 5)
        else:
            continue
        moves.append(mv)
    return multi, moves


def avg(expr):
    if not expr:
        return 0
    tot = 0
    for sign, n, s, k in re.findall(r"([+-]?)\s*(?:(\d*)d(\d+)|(\d+))", expr):
        v = int(k) if k else int(n or 1) * (int(s) + 1) / 2
        tot += -v if sign == "-" else v
    return tot


# ---- the map ----------------------------------------------------------------------------------------

def _foot(x, y, size):
    return [(x + dx, y + dy) for dx in range(size) for dy in range(size)]


def gap_ft(a, asz, b, bsz, per):
    """Feet between two tokens' footprints (5 ft when they're side by side), like movement.distance_ft."""
    gx = max(0, b[0] - (a[0] + asz), a[0] - (b[0] + bsz))
    gy = max(0, b[1] - (a[1] + asz), a[1] - (b[1] + bsz))
    return (max(gx, gy) + 1) * per


class Board:
    def __init__(self, conn, m, me_tok, fly):
        from .maps import BLOCKING, SOLID
        self.m, self.cols, self.rows = m, m["cols"], m["rows"]
        self.block = SOLID if fly else BLOCKING
        self.t = m["terrain"]
        self.size = me_tok["size"]
        self.taken = set()
        for r in conn.execute(
                "SELECT t.x, t.y, t.size, t.kind, t.id, COALESCE(ch.status, cb.status, '') AS st FROM map_tokens t "
                "LEFT JOIN combatants cb ON cb.id = t.combatant_id LEFT JOIN characters ch ON ch.id = COALESCE(t.character_id, cb.character_id) "
                "WHERE t.map_id = ? AND t.id != ?", (m["id"], me_tok["id"])):
            if r["kind"] in ("marker", "trap") or r["st"] in ("dead", "defeated"):
                continue
            self.taken.update(_foot(int(round(r["x"])), int(round(r["y"])), r["size"]))

    def free(self, x, y):
        return all(0 <= a < self.cols and 0 <= b < self.rows and self.t.get(f"{a},{b}") not in self.block and (a, b) not in self.taken
                   for a, b in _foot(x, y, self.size))

    def walk(self, start, limit=None):
        """Squares reachable from start: {(x, y): steps}."""
        seen, q = {start: 0}, deque([start])
        while q:
            x, y = q.popleft()
            if limit is not None and seen[(x, y)] >= limit:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if (dx or dy) and n not in seen and self.free(*n):
                        # no squeezing diagonally between two solid corners
                        if dx and dy and not (self.free(x + dx, y) or self.free(x, y + dy)):
                            continue
                        seen[n] = seen[(x, y)] + 1
                        q.append(n)
        return seen

    def clear_shot(self, a, asz, b, bsz):
        """A clear line of fire: only what you can't see through blocks it (walls, sealed doors, big
        machines), not a terminal or a table you shoot over. Same lines as the heroes' sight (app/vision.py)."""
        from .vision import OPAQUE, _clear
        t, cols, rows = self.t, self.cols, self.rows
        opaque = lambda x, y: not (0 <= x < cols and 0 <= y < rows) or t.get(f"{x},{y}") in OPAQUE
        own = set(_foot(a[0], a[1], asz))
        ax, ay = a[0] + asz / 2, a[1] + asz / 2
        for (tx, ty) in _foot(b[0], b[1], bsz):
            for px, py in ((tx + 0.5, ty + 0.5), (tx + 0.15, ty + 0.15), (tx + 0.85, ty + 0.15), (tx + 0.15, ty + 0.85), (tx + 0.85, ty + 0.85)):
                if _clear(opaque, ax, ay, px, py, (tx, ty), own):
                    return True
        return False


def area_cells(shape, size_ft, per, ox, oy, tx, ty):
    """Squares an area covers: a cone or line from (ox, oy) towards (tx, ty), a circle or square on (tx, ty)."""
    L = size_ft / per
    out = set()
    if shape in ("cone", "line"):
        d = math.hypot(tx - ox, ty - oy) or 1
        ux, uy = (tx - ox) / d, (ty - oy) / d
        for y in range(int(oy - L - 2), int(oy + L + 3)):
            for x in range(int(ox - L - 2), int(ox + L + 3)):
                dx, dy = x + 0.5 - ox, y + 0.5 - oy
                along, across = dx * ux + dy * uy, abs(-dx * uy + dy * ux)
                if shape == "cone" and 0.3 < along <= L + 1e-6 and across <= along * 0.5 + 0.35:
                    out.add((x, y))
                if shape == "line" and 0.3 < along <= L + 1e-6 and across <= 0.55:
                    out.add((x, y))
    else:
        for y in range(int(ty - L - 1), int(ty + L + 2)):
            for x in range(int(tx - L - 1), int(tx + L + 2)):
                dx, dy = x + 0.5 - tx, y + 0.5 - ty
                if (shape == "circle" and math.hypot(dx, dy) <= L + 1e-6) or (shape == "square" and abs(dx) <= L / 2 and abs(dy) <= L / 2):
                    out.add((x, y))
    return out


# ---- one enemy's turn ---------------------------------------------------------------------------------

def _tactics(c):
    from .prison_monsters import TACTICS
    sb = c["statblock"] or {}
    return dict(TACTICS.get(sb.get("base_name") or c["name"], {}))


def _active(conds):
    return {str(x.get("name") or "").lower() for x in conds if isinstance(x, dict) and not x.get("expired")}


def take_turn(ctx, cid):
    """The enemy whose turn it is acts. Returns what it did, as lines."""
    from .combat import add_conditions, apply_hp, drop_conditions
    from .movement import _live_map, _token_of, ft_per_square, turn_info
    conn, eid = ctx.conn, ctx.enc["id"]
    c = ctx.combatant(cid)
    if ctx.enc["status"] != "active" or ctx.enc["current_id"] != cid:
        raise F.ApiError("It isn't their turn")
    if c["linked"] or c["kind"] != "enemy":
        raise F.ApiError("Only enemies act on their own — heroes are played by their players")
    if c["hp"] <= 0 or c["status"] in ("dead", "defeated", "fled"):
        return [f"{c['name']} is down and can't act"]
    mrow = _live_map(conn, eid)
    if mrow is None:
        raise F.ApiError("Enemies act on their own on a battle map: link this fight to a map first")
    from .maps import map_dict
    m = map_dict(mrow)
    me = _token_of(conn, m["id"], cid)
    if me is None:
        raise F.ApiError(f"{c['name']} has no token on the map")
    me = conn.execute("SELECT * FROM map_tokens WHERE map_id = ? AND combatant_id = ? LIMIT 1", (m["id"], cid)).fetchone() or \
        conn.execute("SELECT * FROM map_tokens WHERE map_id = ? AND x = ? AND y = ? LIMIT 1", (m["id"], me["x"], me["y"])).fetchone()
    per = ft_per_square(m)
    tac = _tactics(c)
    sb = c["statblock"] or {}
    st = sb.get("ai") or {}
    lines, rnd = [], random.SystemRandom()
    DMV = {"role": "dm", "name": c["name"]}
    ids = {"combatant_id": cid, "encounter_id": eid}

    def say(text):
        lines.append(text)
        ctx.log("system", text)

    # 1. start of turn: regeneration, recharges
    if tac.get("regen") and 0 < c["hp"] < c["max_hp"]:
        apply_hp(ctx, cid, {"op": "heal", "amount": int(tac["regen"])}, "regeneration")
        c = ctx.combatant(cid)
    spent = st.get("spent") or {}
    for mv_name, low in list(spent.items()):
        r = rnd.randint(1, 6)
        if r >= low:
            spent.pop(mv_name)
            say(f"{c['name']}'s {mv_name} recharges (rolled {r})")
    if _active(c["conditions"]) & CANT_ACT:
        say(f"{c['name']} can't act this turn ({', '.join(sorted(_active(c['conditions']) & CANT_ACT))})")
        _save_state(ctx, c, st, spent)
        return lines
    phase2 = bool(sb.get("has_phase2")) and c["hp"] * 2 <= c["max_hp"]
    multi, moves = parse_moves((sb.get("attacks") or "") + ("\n" + sb.get("phase2", "") if phase2 else ""))
    if tac.get("overclock") and c["hp"] * 2 <= c["max_hp"]:
        multi += 1
    moves = [mv for mv in moves if not (mv["recharge"] and mv["name"] in spent)]
    if not moves:
        say(f"{c['name']} has nothing to attack with")
        return lines

    # 2. who to go after: everyone not on its side, standing on the map
    foes = []
    for o in ctx.combatants():
        if o["kind"] == "enemy" or o["hp"] <= 0 or o["status"] in ("dead", "defeated", "fled", "unconscious") or o["hidden"]:
            continue
        t = _token_of(conn, m["id"], o["id"])
        if t:
            foes.append({"c": o, "at": (int(round(t["x"])), int(round(t["y"]))), "size": t["size"]})
    if not foes:
        say(f"{c['name']} looks around: nobody to fight")
        return lines
    here = (int(round(me["x"])), int(round(me["y"])))
    board = Board(conn, m, me, tac.get("fly"))
    reach_map = board.walk(here)
    near = lambda f: min((s for p, s in reach_map.items() if gap_ft(p, me["size"], f["at"], f["size"], per) <= per), default=99) \
        if reach_map else 99
    mode = tac.get("target", "nearest")
    if mode == "weakest":
        foes.sort(key=lambda f: (f["c"]["hp"] / max(1, f["c"]["max_hp"]), near(f)))
    elif mode == "isolated":
        def lonely(f):
            others = [g for g in foes if g is not f]
            return -min((gap_ft(f["at"], f["size"], g["at"], g["size"], per) for g in others), default=999)
        foes.sort(key=lambda f: (lonely(f), near(f)))
    else:
        foes.sort(key=lambda f: (near(f), gap_ft(here, me["size"], f["at"], f["size"], per)))
    target = foes[0]

    melee = sorted([mv for mv in moves if mv["kind"] == "melee"], key=lambda mv: -avg(mv["dmg"]))
    ranged = sorted([mv for mv in moves if mv["kind"] == "ranged"], key=lambda mv: -avg(mv["dmg"]))
    areas = [mv for mv in moves if mv["kind"] == "area"]
    style = tac.get("style") or ("ranged" if ranged and (not melee or avg(ranged[0]["dmg"]) >= avg(melee[0]["dmg"])) else "melee")
    info = turn_info(conn, cid) or {}
    steps = (info.get("budget") or 0) // per
    if info.get("held"):
        steps = 0

    def adjacent_foe(p):
        return any(gap_ft(p, me["size"], f["at"], f["size"], per) <= per for f in foes)

    def can_hit(p, mv, f):
        d = gap_ft(p, me["size"], f["at"], f["size"], per)
        if mv["kind"] == "melee":
            return d <= mv["reach"]
        if mv["kind"] == "ranged":
            return d <= mv["long"] and board.clear_shot(p, me["size"], f["at"], f["size"])
        return False

    # 3. where to stand
    within = {p: s for p, s in reach_map.items() if s <= steps}
    goal_dist = board_dist_to(board, target, me["size"], per, here)
    if style in ("ranged", "kite"):
        want_range = True
    elif style == "adaptive":
        want_range = not (melee and any(can_hit(p, melee[0], target) for p in within))
    else:
        want_range = not melee
    best, how = here, None
    if want_range and ranged:
        mv = ranged[0]
        keep = int(tac.get("keep") or 0)
        ok = [p for p in within if can_hit(p, mv, target)]
        good = [p for p in ok if gap_ft(p, me["size"], target["at"], target["size"], per) <= mv["range"] and not adjacent_foe(p)
                and min(gap_ft(p, me["size"], f["at"], f["size"], per) for f in foes) >= keep * per]
        pool = good or [p for p in ok if not adjacent_foe(p)] or ok
        if pool:
            best = here if here in pool else min(pool, key=lambda p: within[p])
            how = "shoot"
    if how is None and melee:
        ok = [p for p in within if can_hit(p, melee[0], target)]
        if ok:
            best, how = min(ok, key=lambda p: within[p]), "melee"
    if how is None:
        # can't attack it this turn: dash towards it (twice the move) — or shoot someone else in range
        other = next(((p, f) for f in foes[1:] for p in sorted(within, key=within.get)
                      if (melee and can_hit(p, melee[0], f)) or (ranged and can_hit(p, ranged[0], f))), None)
        if other:
            best, target = other
            how = "melee" if melee and can_hit(best, melee[0], target) else "shoot"
        else:
            far = {p: s for p, s in reach_map.items() if s <= steps * 2}
            if far and goal_dist:
                best = min(far, key=lambda p: (goal_dist.get(p, 999), far[p]))
            how = "dash"
    if best != here:
        conn.execute("UPDATE map_tokens SET x = ?, y = ?, updated_at = ? WHERE id = ?", (best[0], best[1], now_iso(), me["id"]))
        moved = max(abs(best[0] - here[0]), abs(best[1] - here[1]))
        say(f"{c['name']} {'dashes' if how == 'dash' else 'flies' if tac.get('fly') else 'moves'} {reach_map.get(best, moved) * per} ft"
            + (" towards " + target["c"]["name"] if how == "dash" else ""))
        from .play import _zone_check
        _zone_check(conn, m)  # walking into Spirit Guardians hurts
        c = ctx.combatant(cid)
        if c["hp"] <= 0:
            return lines
    if how == "dash":
        if best == here:
            say(f"{c['name']} holds its position: no way to reach or get a clear shot at anyone")
        _save_state(ctx, c, st, spent)
        return lines

    # 4. attack
    cloaked = tac.get("cloak") and st.get("cloaked", True)
    attacked = False
    # an area move first, when it catches two or more of them (or nothing else reaches)
    if areas:
        mv = areas[0]
        center = lambda f: (f["at"][0] + f["size"] / 2, f["at"][1] + f["size"] / 2)
        ox, oy = best[0] + me["size"] / 2, best[1] + me["size"] / 2
        plans = []
        for f in foes:
            fx, fy = center(f)
            if mv["shape"] == "circle" and mv["range"] and math.hypot(fx - ox, fy - oy) * per > mv["range"] + per:
                continue
            if mv["shape"] in ("cone", "line") and math.hypot(fx - ox, fy - oy) * per > mv["size"] + per:
                continue
            cells = area_cells(mv["shape"], mv["size"], per, ox, oy, fx, fy)
            caught = [g for g in ctx.combatants() if g["id"] != cid and g["hp"] > 0 and g["status"] not in ("dead", "defeated")]
            hit = []
            for g in caught:
                t = _token_of(conn, m["id"], g["id"])
                if t and set(_foot(int(round(t["x"])), int(round(t["y"])), t["size"])) & cells:
                    hit.append(g)
            score = sum(1 for g in hit if g["kind"] != "enemy") - sum(1 for g in hit if g["kind"] == "enemy")
            plans.append((score, (fx, fy), hit))
        plans.sort(key=lambda p: -p[0])
        if plans and (plans[0][0] >= 2 or (plans[0][0] >= 1 and how is None)):
            _, (fx, fy), hit = plans[0]
            _area(ctx, c, mv, hit, (fx, fy) if mv["shape"] in ("circle", "square") else None, DMV, ids, say, rnd)
            if mv["recharge"]:
                spent[mv["name"]] = mv["recharge"]
            attacked = True
            multi = 0
    for i in range(multi):
        target_now = ctx.combatant(target["c"]["id"])
        if target_now["hp"] <= 0 or target_now["status"] in ("dead", "defeated", "unconscious"):
            alive = [f for f in foes if ctx.combatant(f["c"]["id"])["hp"] > 0
                     and ((melee and can_hit(best, melee[0], f)) or (ranged and can_hit(best, ranged[0], f)))]
            if not alive:
                break
            target = alive[0]
        mv = melee[0] if melee and can_hit(best, melee[0], target) else (ranged[0] if ranged and can_hit(best, ranged[0], target) else None)
        if mv is None:
            break
        tc = ctx.combatant(target["c"]["id"])
        adv = bool(cloaked and i == 0) or (tac.get("adv_bloodied") and tc["hp"] * 2 <= tc["max_hp"])
        dis = mv["kind"] == "ranged" and adjacent_foe(best)
        extra = []
        if cloaked and i == 0 and tac.get("sneak"):
            extra.append(tac["sneak"])
        if tac.get("bonus_bloodied") and tc["hp"] * 2 <= tc["max_hp"]:
            extra.append(tac["bonus_bloodied"])
        if mv["kind"] == "ranged" and gap_ft(best, me["size"], target["at"], target["size"], per) > mv["range"]:
            dis = True  # a long shot
        _strike(ctx, c, mv, tc, "advantage" if adv and not dis else "disadvantage" if dis and not adv else "normal", extra, DMV, ids, say, rnd)
        attacked = True
    if tac.get("cloak"):
        inv = [x for x in ctx.combatant(cid)["conditions"] if str(x.get("name")).lower() == "invisible" and not x.get("expired")]
        if attacked and cloaked:
            st["cloaked"] = False
            if inv:
                drop_conditions(ctx, ctx.combatant(cid), {x["id"] for x in inv}, quiet=True)
            say(f"{c['name']}'s cloak flickers off")
        elif not attacked:
            st["cloaked"] = True
            if not inv:
                add_conditions(ctx, [cid], "Invisible", None, note="cloaking field")
    _save_state(ctx, ctx.combatant(cid), st, spent)
    return lines


def board_dist_to(board, target, size, per, start=None):
    """Steps from every square to a square next to the target, walking round walls and round whoever's
    in the way (if there's a way round; if not, as if nobody were in the way, to get as close as it can)."""
    with_people = _dist_to(board, target, size, keep_people=True)
    if start is None or start in with_people or any(n in with_people for n in board.walk(start, 1)):
        return with_people
    return _dist_to(board, target, size, keep_people=False)


def _dist_to(board, target, size, keep_people):
    goals = set()
    tx, ty = target["at"]
    for x in range(tx - size, tx + target["size"] + 1):
        for y in range(ty - size, ty + target["size"] + 1):
            goals.add((x, y))
    saved = board.taken
    board.taken = saved - set(_foot(tx, ty, target["size"])) if keep_people else set()
    seen, q = {}, deque()
    for g in goals:
        if board.free(*g):
            seen[g] = 0
            q.append(g)
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx or dy) and n not in seen and board.free(*n):
                    seen[n] = seen[(x, y)] + 1
                    q.append(n)
    board.taken = saved
    return seen


def _save_state(ctx, c, st, spent):
    sb = dict(c["statblock"] or {})
    st = dict(st, spent=spent)
    sb["ai"] = st
    ctx.conn.execute("UPDATE combatants SET statblock = ? WHERE id = ?", (json.dumps(sb), c["id"]))


def _hero_save(ctx, g, ab, dc, DMV, ids, rnd):
    from .rolls import save_roll
    from .rules import derived
    if g["linked"]:
        row = ctx.conn.execute("SELECT * FROM characters WHERE id = ?", (g["character_id"],)).fetchone()
        bonus = derived(F.decode_row(row, F.CHARACTER))["saves"][ab]
    else:
        score = int(((g["statblock"] or {}).get("abilities") or {}).get(ab) or 10)
        bonus = (score - 10) // 2
    r = dice.roll(f"1d20{bonus:+d}")
    ok = r["total"] >= dc
    save_roll(ctx.conn, {"role": "dm", "name": g["name"]}, ctx.enc["campaign_id"], r, label=f"{ab.upper()} save (DC {dc})", kind="save",
              subject=g["name"], ids={"combatant_id": g["id"], "encounter_id": ctx.enc["id"], "character_id": g.get("character_id")},
              outcome="Saved" if ok else "Failed")
    return ok, r["total"]


def _strike(ctx, c, mv, tc, mode, extra, DMV, ids, say, rnd):
    from .combat import add_conditions, apply_hp
    from .maps import attack_fx
    from .reactions import note_attack
    from .rolls import save_roll
    r = dice.roll(f"1d20{mv['bonus']:+d}", mode=mode)
    nat = r.get("natural")
    crit, hit = nat == 20, nat == 20 or (nat != 1 and r["total"] >= tc["ac"])
    save_roll(ctx.conn, DMV, ctx.enc["campaign_id"], r, label=f"{mv['name']} at {tc['name']}", kind="attack", subject=c["name"], ids=ids,
              outcome="Critical hit!" if crit else "Hit" if hit else "Miss")
    how = "crit" if crit else "hit" if hit else "miss"
    adv = " with advantage" if mode == "advantage" else " with disadvantage" if mode == "disadvantage" else ""
    if not hit:
        say(f"{c['name']} — {mv['name']} at {tc['name']}{adv}: {r['total']}, misses")
        attack_fx(ctx.conn, ctx.enc["id"], c["id"], [(tc["id"], how)], mv["name"], "damage", mv["type"], None, mv["look"])
        note_attack(ctx, c["id"], [tc["id"]])
        return
    expr = "+".join([mv["dmg"]] + list(extra)) if mv["dmg"] else "+".join(extra) or "1"
    d = dice.roll(expr, crit=crit)
    save_roll(ctx.conn, DMV, ctx.enc["campaign_id"], d, label=f"{mv['name']} damage" + (" (crit)" if crit else ""), kind="damage",
              subject=c["name"], ids=ids)
    say(f"{c['name']} — {mv['name']} at {tc['name']}{adv}: {r['total']}, {'CRITICAL ' if crit else ''}hit for {d['total']} {mv['type']} damage".rstrip())
    attack_fx(ctx.conn, ctx.enc["id"], c["id"], [(tc["id"], how)], mv["name"], "damage", mv["type"], None, mv["look"])
    ctx.attack = {"by": c["id"], "name": mv["name"], "type": mv["type"], "ranged": mv["kind"] == "ranged"}
    apply_hp(ctx, tc["id"], {"op": "damage", "amount": d["total"]}, "from " + c["name"])
    ctx.attack = None
    note_attack(ctx, c["id"], [tc["id"]])
    tc = ctx.combatant(tc["id"])
    if mv["cond"] and tc["hp"] > 0:
        if mv["save"]:
            ok, tot = _hero_save(ctx, tc, mv["save"][1], mv["save"][0], DMV, ids, rnd)
            if ok:
                say(f"{tc['name']} resists ({mv['save'][1].upper()} save {tot} vs DC {mv['save'][0]})")
                return
        add_conditions(ctx, [tc["id"]], mv["cond"], mv["rounds"], caster=c if mv["rounds"] else None, note=mv["name"])


def _area(ctx, c, mv, hit, at, DMV, ids, say, rnd):
    from .combat import add_conditions, apply_hp
    from .maps import attack_fx
    from .rolls import save_roll
    d = dice.roll(mv["dmg"]) if mv["dmg"] else None
    if d:
        save_roll(ctx.conn, DMV, ctx.enc["campaign_id"], d, label=f"{mv['name']} damage", kind="damage", subject=c["name"], ids=ids)
    names, hows = [], []
    dc, ab = mv["save"] if mv["save"] else (10, "dex")
    for g in hit:
        ok, tot = _hero_save(ctx, g, ab, dc, DMV, ids, rnd)
        hows.append((g["id"], "saved" if ok else "failed"))
        amount = (d["total"] // 2 if ok else d["total"]) if d else 0
        if amount:
            ctx.attack = {"by": c["id"], "name": mv["name"], "type": mv["type"], "ranged": None}
            apply_hp(ctx, g["id"], {"op": "damage", "amount": amount}, "from " + c["name"])
            ctx.attack = None
        names.append(f"{g['name']} {'saves' if ok else 'fails'} ({amount})")
        g2 = ctx.combatant(g["id"])
        if mv["cond"] and not ok and g2["hp"] > 0:
            add_conditions(ctx, [g["id"]], mv["cond"], mv["rounds"], caster=c if mv["rounds"] else None, note=mv["name"])
    area = {"kind": mv["shape"], "size": mv["size"]} | ({"at": [round(at[0], 2), round(at[1], 2)]} if at else {})
    attack_fx(ctx.conn, ctx.enc["id"], c["id"], hows, mv["name"], "damage", mv["type"], area, mv["look"])
    say(f"{c['name']} uses {mv['name']}" + (f" ({d['total']} {mv['type']} damage, DC {dc} {ab.upper()} save for half)" if d else "")
        + ": " + (", ".join(names) or "it catches nobody"))


# ---- the API ----------------------------------------------------------------------------------------

def act(ctx, then_next=False):
    """The current enemy acts (and the turn moves on if asked). Returns the lines."""
    from .combat import next_turn
    cid = ctx.enc["current_id"]
    lines = take_turn(ctx, cid)
    if then_next:
        next_turn(ctx)
    return lines


@bp.post("/encounters/<int:eid>/auto-turn")
def api_auto_turn(eid):
    """{next: true} also ends its turn afterwards. The whole turn is one step for Undo last action."""
    from .combat import Ctx, encounter_state
    from .spells import record, snapshot
    data = request.get_json(silent=True) or {}
    with tx() as conn:
        ctx = Ctx(conn, eid)
        snap = snapshot(ctx)
        name = ctx.current_name()
        lines = act(ctx, bool(data.get("next")))
        record(ctx, snap, f"{name}'s turn")
        conn.execute("UPDATE encounters SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), eid))
        for mp in conn.execute("SELECT id FROM maps WHERE encounter_id = ?", (eid,)).fetchall():
            conn.execute("UPDATE maps SET rev = rev + 1, updated_at = ? WHERE id = ?", (now_iso(), mp["id"]))
    return jsonify(encounter_state(eid) | {"did": lines})


def auto_enemies(ctx, depth=0):
    """'Enemies act on their own': after the turn moves on to an enemy on a map, it acts and passes
    the turn on, and so on until it's a hero's turn (or 30 turns, so nothing can run away)."""
    from .campaigns import get_campaign
    from .combat import next_turn
    if depth > 30 or ctx.enc["status"] != "active" or not get_campaign(ctx.enc["campaign_id"])["settings"]["loot"].get("auto_act"):
        return
    try:
        c = ctx.combatant(ctx.enc["current_id"])
    except F.NotFound:
        return
    if c["linked"] or c["kind"] != "enemy":
        return
    from .movement import _live_map, _token_of
    m = _live_map(ctx.conn, ctx.enc["id"])
    if m is None or _token_of(ctx.conn, m["id"], c["id"]) is None:
        return
    if not any(o["kind"] != "enemy" and o["hp"] > 0 for o in ctx.combatants()):
        return
    try:
        take_turn(ctx, c["id"])
    except F.ApiError:
        return
    next_turn(ctx, _auto_depth=depth + 1)
