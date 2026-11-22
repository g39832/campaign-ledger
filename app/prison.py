"""Stocking the abandoned prison: when one is made (or a new layout, or the next level), its rooms
get their enemies (hidden until a hero walks in, so the usual room fight starts) and their chests.

- Cells: supply crates, med chests, the odd inmate, and the infiltrator who carries the Lab keycard.
- Security office: guards (one carries the Security keycard) and the Restricted Security Vault.
- Med bay, generator room, supply depot, mess hall, interrogation room: their own chests and guards.
- Behind sealed doors: the Hidden armory (Security keycard), the Smugglers' stash (a hidden panel),
  the Experimental lab (Lab keycard) and the Restricted vault with the Legendary Supply Cache
  (the Warden's access card, which the warden always drops).
- The warden's command deck: the boss and its guards. Deeper levels bring the heavier machines.
"""
import random

from flask import current_app

from . import fields as F
from .chests import add_chest
from .db import new_uid, now_iso
from .prison_monsters import NAMES, portrait_file


def ensure_creatures(conn, campaign_id, names=None):
    """The ten prison enemies (or these names: the lab's) in the campaign's creature library (with their
    pictures). Ones the DM already has (and maybe edited) are used as they are. Returns {name: (stat block, creature id)}."""
    from .monster_book import BY_NAME
    out = {}
    for name in names or NAMES:
        row = conn.execute("SELECT * FROM creatures WHERE lower(name) = lower(?) AND (campaign_id = ? OR campaign_id IS NULL) "
                           "ORDER BY campaign_id IS NULL LIMIT 1", (name, campaign_id)).fetchone()
        try:
            pic = portrait_file(current_app.config["UPLOAD_DIR"], name)
        except OSError:
            pic = None
        if row is None:
            ts = now_iso()
            cid = F.insert(conn, "creatures", F.CREATURE, F.validate_new(F.CREATURE, BY_NAME[name]),
                           {"uid": new_uid(), "campaign_id": campaign_id, "created_at": ts, "updated_at": ts})
            if pic:
                conn.execute("UPDATE creatures SET portrait = ? WHERE id = ?", (pic, cid))
            row = conn.execute("SELECT * FROM creatures WHERE id = ?", (cid,)).fetchone()
        elif pic and not row["portrait"]:
            conn.execute("UPDATE creatures SET portrait = ? WHERE id = ?", (pic, row["id"]))
        out[name] = (F.decode_row(row, F.CREATURE), row["id"])
    return out


def _cells_of(box):
    x0, y0, x1, y1 = box
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def furnish(conn, map_id):
    from . import maps as M
    m = M.map_dict(M._map_row(conn, map_id))
    d = m.get("dungeon") or {}
    if d.get("theme") != "futureprison":
        return
    level = int(d.get("level") or 1)
    rnd = random.Random(int(d.get("seed") or 1) * 31 + level)
    lib = ensure_creatures(conn, m["campaign_id"])
    used = set()  # squares with a chest or a monster on them

    def open_cells(room, size=1):
        out = []
        for x, y in _cells_of(room["box"]):
            sq = [(x + dx, y + dy) for dx in range(size) for dy in range(size)]
            if all(m["terrain"].get(f"{a},{b}") not in M.BLOCKING and (a, b) not in used and room["box"][0] <= a <= room["box"][2]
                   and room["box"][1] <= b <= room["box"][3] for a, b in sq):
                out.append((x, y))
        return out

    def chest(kind, room, lock=None, back=True):
        spots = open_cells(room)
        if not spots:
            return
        # along the far wall of the room, where a crate would be stacked
        spots.sort(key=lambda p: (p[1] != room["box"][1] and p[1] != room["box"][3], rnd.random()) if back else rnd.random())
        x, y = spots[0]
        used.add((x, y))
        add_chest(conn, map_id, kind, x, y, lock, False, "", "placed", None, rnd.randrange(1, 2 ** 31))

    def foe(name, room, n=1, carries=None):
        block, cid = lib[name]
        size = 2 if str(block.get("creature_type") or "").startswith("Large") else 1
        spots = open_cells(room, size)
        if not spots:
            return
        cx, cy = (room["box"][0] + room["box"][2]) / 2, (room["box"][1] + room["box"][3]) / 2
        spots.sort(key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))
        for k in range(n):
            if k >= len(spots):
                break
            x, y = spots[k]
            M.add_monsters(conn, m, block, name, cid, 1, x, y, hidden=True, extra={"carries": carries} if carries and k == 0 else None)
            for dx in range(size):
                for dy in range(size):
                    used.add((x + dx, y + dy))

    rooms = d["rooms"]
    by = {}
    for r in rooms:
        by.setdefault(r["name"], []).append(r)
    boss = next(r for r in rooms if r["kind"] == "boss")
    start = next(r for r in rooms if r["kind"] == "start")
    cells = [r for r in rooms if r["kind"] == "cell"]
    rnd.shuffle(cells)

    chest("supply", start)
    # the cells: one holds the infiltrator with the Lab keycard, a few hold inmates, many hold supplies
    if cells:
        foe("Stealth Infiltrator", cells[0], carries=["labkey"])
        chest("supply", cells[0])
    inmates = 0
    for c in cells[1:]:
        roll = rnd.random()
        if roll < 0.18 and inmates < 2 + level:
            foe("Inmate Enforcer", c)
            chest(rnd.choice(["supply", "military"]), c)  # what they were guarding
            inmates += 1
        elif roll < 0.5:
            chest("supply", c)
        elif roll < 0.62:
            chest("medical", c)
    # the side rooms
    office = (by.get("Security office") or [None])[0] or boss
    foe("Cybernetic Prison Guard", office, 2, carries=["seckey"])
    foe("Security Drone", office)
    chest("vault", office)
    if office is not boss:
        chest("supply", office)
    for r in by.get("Med bay", []):
        foe("Experimental Prisoner", r)
        chest("medical", r)
        chest("medical", r)
    for r in by.get("Generator room", []):
        if level >= 2:
            foe("Sentinel Unit", r)
        else:
            foe("Riot Suppressor", r, 2)
        chest("military", r)
    for r in by.get("Supply depot", []):
        foe("Inmate Enforcer", r, 2)
        chest("supply", r)
        chest("supply", r)
    for r in by.get("Mess hall", []):
        foe("Riot Suppressor", r)
        foe("Inmate Enforcer", r)
        chest("supply", r)
    for r in by.get("Interrogation room", []):
        foe("Cybernetic Prison Guard", r)
        chest("military", r)
    # behind the sealed doors
    for r in rooms:
        if r["kind"] == "secret" and r.get("needs"):       # the Hidden armory
            chest("military", r)
            chest("vault", r, lock="")                     # (the door was the lock)
            foe("Riot Suppressor", r)
        elif r["kind"] == "secret":                        # the Smugglers' stash: nobody guards it
            chest("experimental", r)
            chest("supply", r)
            chest("medical", r)
        elif r["kind"] == "lab":
            foe("Prototype Cyborg", r)
            if level >= 2:
                foe("Experimental Prisoner", r)
            chest("experimental", r)
            chest("experimental", r)
        elif r["kind"] == "vault":
            if level >= 2:
                foe("Execution Unit", r)
            else:
                foe("Security Drone", r, 2)
            chest("legendary", r)
            chest("vault", r, lock="")
    # the warden's deck
    foe("Prison Warden", boss)
    foe("Cybernetic Prison Guard", boss, 2)
    if level >= 3:
        foe("Execution Unit", boss)
    chest("military", boss)
    chest("medical", boss)
    M._bump(conn, map_id)


def clear(conn, map_id):
    """Before a new layout: the old chests go, and the enemies placed for the old one leave the map's
    encounter (only if that fight hasn't started)."""
    conn.execute("DELETE FROM chests WHERE map_id = ?", (map_id,))
    row = conn.execute("SELECT m.encounter_id, e.status FROM maps m LEFT JOIN encounters e ON e.id = m.encounter_id WHERE m.id = ?",
                       (map_id,)).fetchone()
    if row and row["encounter_id"] and row["status"] != "active":
        conn.execute("DELETE FROM combatants WHERE encounter_id = ? AND kind = 'enemy' AND id NOT IN "
                     "(SELECT combatant_id FROM map_tokens WHERE combatant_id IS NOT NULL)", (row["encounter_id"],))
