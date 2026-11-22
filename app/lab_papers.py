"""Mysterious papers in the laboratory (2026-11-15 session: the party comes for the coordinates of
the new space station).

Every floor has a few loose papers lying in its rooms. A hero who stands next to one and taps Read
gets it as a handout (it pops up on their screen and stays in their Handouts), so only the reader
sees it until they share it with the table. The DM sees every paper's text in the map's chest list.

What the clues build towards, a floor at a time (DM only: see DM_KEY):
  - Steven Voss runs Project IRONCLAD: the mechs and the relay drones.
  - Someone called "the Director" runs Project CHIMERA: the mutations.
  - Chimera's "E series" of test subjects, and the one graft that took (earth / stone). That points
    at Moni Easter, without ever saying her name.
  - The top floor has the code for the new station's coordinates (a data chip the party can take).
    It is found here, in the laboratory, not on a ship.

To change a clue, edit its text below. Papers already on a map keep the text they were made with
(delete them on the DM map and call place() again to put fresh ones down).
"""
import random

from .db import now_iso

DIRECTOR = "the Director"  # the mutation project's leader, never named in the papers

DM_KEY = ("IRONCLAD = Steven Voss (mechs, relay drones). CHIMERA = the Director (mutations). "
          "The E series ends with E-5, the stone graft that took and then went missing: Moni Easter. "
          "Don't confirm it yet. The station coordinates code is found in the lab itself: floor 5, the "
          "Station coordinates printout in the Director's office (not on any ship).")

# floor -> [(title, text)]. The last paper on floor 5 carries the coordinates chip.
PAPERS = {
    1: [
        ("Visitor log (torn)",
         "LEVEL ACCESS — SIGN IN BELOW\n\n"
         "Wing A · Mechanics · S. VOSS ............ clearance OMEGA\n"
         "Wing B · Biology · THE DIRECTOR ......... clearance OMEGA\n\n"
         "Staff of one wing do NOT enter the other wing. No exceptions.\n\n"
         "(The rest of the page has been torn away.)"),
        ("Staff memo",
         "TO ALL STAFF\n\n"
         "This building houses two projects: IRONCLAD and CHIMERA. They share the power, the lift and "
         "the cafeteria. They do not share notes.\n\n"
         "Anyone caught carrying files between the two wings will be reassigned. Permanently.\n\n— Administration"),
        ("Sticky note",
         "The lift code changes on every floor.\n"
         "The station coordinates code is NOT kept down here. The Director's office, top floor only.\n"
         "Don't ask me again. — R."),
    ],
    2: [
        ("Requisition form",
         "PROJECT IRONCLAD — PARTS REQUEST\n\n"
         "40 tons hull steel\n12 relay cores\n6 walking frames, pilot seats removed\n\n"
         "Purpose: autonomous mechs, steered by relay drone.\n\n"
         "APPROVED: S. Voss, Ironclad lead"),
        ("Drone test notes",
         "Test 14. The test subject cast a spell at the relay drone. The drone caught the spell, "
         "held it, and threw it back at the subject thirty seconds later.\n\n"
         "Voss laughed for a full minute.\n\n"
         "Note to self: never cast anything near his drones. Never."),
        ("Incident report",
         "INCIDENT REPORT · WING A (IRONCLAD)\n\n"
         "Voss doesn't only build machines. He makes magic items too: rings, gauntlets, a cloak that hums. "
         "He forges the metal himself and works the magic into it.\n\n"
         "Today a test subject grabbed one of his gauntlets off the bench and ran for the door. "
         "Voss didn't chase him. He just lifted his hand, and the gauntlet tore itself off the subject's arm "
         "and flew back across the room into his palm.\n\n"
         "He said, without looking up: \"Everything I make comes home.\"\n\n"
         "Recommendation: nobody steals from Wing A."),
        ("Coffee-stained page",
         "...Chimera keeps stealing our power at night. The lights in Wing B never go out.\n\n"
         f"Voss says {DIRECTOR} \"grows things that should have stayed buried.\" I asked what he meant. "
         "He said to ask the E series. I don't know what that is."),
    ],
    3: [
        ("Chimera subject log, page 1",
         "PROJECT CHIMERA — E SERIES\n\n"
         "E-1 · graft: fire ........ rejected\n"
         "      graft core recovered, sealed into: WorldFlare Glo—\n"
         "E-2 · graft: water ....... rejected\n"
         "      graft core recovered, sealed into: Moonlit ba—\n"
         "E-3 · graft: wind ........ rejected\n"
         "      graft core recovered, sealed into: Gale fl—\n"
         "E-4 · graft: lightning ... rejected\n"
         "      graft core recovered, sealed into: Thunderforged sig—\n\n"
         "(The right edge of the page is torn off.)\n\n"
         "Subjects returned to holding. Cores sent to Wing A for casing. Continue to E-5.\n\n"
         f"— signed for {DIRECTOR}"),
        ("Mech blueprint, scrap",
         "IRONCLAD FRAME MK-IV\n\n"
         "No pilot. Steered from the Voss workshop through the relay drones.\n"
         "Weak point: the relay core on its back. If the drone near it goes down, the frame goes deaf.\n\n"
         "(Someone has circled the relay core three times in red.)"),
        ("Unsigned note",
         "I don't care what the Director says. They were people, not specimens.\n\n"
         "I left the back door of holding open. If anyone finds this: I'm sorry it was only one."),
    ],
    4: [
        ("Chimera subject log, page 2",
         "E-5 · graft: STONE ..... TOOK\n\n"
         "The subject moves rock with bare hands. Calm. Focused. Strikes like a hammer. "
         "Showed none of the rejection of E-1 to E-4.\n\n"
         "LOST during transfer to the new station. Holding door found open.\n\n"
         f"{DIRECTOR} wants E-5 found and brought home. Alive."),
        ("Ironclad shipping manifest",
         "SHIPPED TO THE STATION\n\n"
         "Frames 1 to 6 ............ sent\n"
         "Relay drones (24) ........ sent\n"
         "Chimera tanks (8) ......... sent, under protest — S. Voss\n\n"
         "The station's coordinates code stays in THIS lab: top floor, the Director's office."),
        ("Photograph",
         "A photo of two people in lab coats cutting a ribbon in front of this lab's front doors. One wears "
         "thick work goggles: \"S. Voss\" is written under him.\n\n"
         "The other person's face has been scratched out with a pen. Under it, someone wrote: THE DIRECTOR."),
    ],
    5: [
        ("Letter on the desk",
         "Steven,\n\n"
         "When the station is ready, Chimera moves up with Ironclad. Your machines, my children. "
         "Bring the surviving subjects. All of them.\n\n"
         "And if E-5 turns up, you call ME first. Not your son.\n\n"
         f"— {DIRECTOR.capitalize()}"),
        ("Shredded page",
         "(Only a strip survived the shredder.)\n\n"
         "...E-5 may be close. A band of travellers came down the mountain road, and one of them "
         "fights with stone. Watch the lift. Don't let them off this planet..."),
        ("Station coordinates printout",
         "LAB RECORDS · RESTRICTED\n\n"
         "The coordinates code for the new station:\n"
         "ORBIT-7 / 214.6 / -12.08 / RING C\n\n"
         "This laboratory is the only place the code is kept.\n\n"
         "A data chip with the code is clipped to the printout."),
    ],
}
COORDS_CHIP = {"name": "Station coordinates chip", "type": "key", "rarity": "legendary", "weight": 0, "unique": True,
               "desc": "A data chip found in the laboratory, holding the code for the new space station's coordinates "
                       "(ORBIT-7 / 214.6 / -12.08 / RING C). The lab was the only place it was kept."}


def note_item(title, text, rnd):
    return {"id": "%08x" % rnd.getrandbits(32), "name": title, "qty": 1, "rarity": "common", "type": "note",
            "weight": 0, "desc": text}


def papers_for(level, rnd):
    """[(title, [items])] for one floor."""
    out = []
    for i, (title, text) in enumerate(PAPERS.get(level, [])):
        items = [note_item(title, text, rnd)]
        if level == 5 and i == len(PAPERS[5]) - 1:
            items.append(dict(COORDS_CHIP, id="%08x" % rnd.getrandbits(32), qty=1))
        out.append((title, items))
    return out


def place(conn, map_id):
    """Put this floor's papers down: only the ones it doesn't have yet (so it can run again after new ones are added).
    Each paper goes in a different room where it can, on open floor, never on a chest or a token."""
    from . import maps as M
    from .chests import add_chest
    from .prison import _cells_of
    m = M.map_dict(M._map_row(conn, map_id))
    d = m.get("dungeon") or {}
    if d.get("theme") != "lab":
        return 0
    have = {r["label"] for r in conn.execute("SELECT label FROM chests WHERE map_id = ? AND kind = 'papers'", (map_id,))}
    level = int(d.get("level") or 1)
    rnd = random.Random(int(d.get("seed") or 1) * 53 + level)  # its own dice: the floor's enemies and lockers don't change
    used = {(r["x"], r["y"]) for r in conn.execute("SELECT x, y FROM chests WHERE map_id = ?", (map_id,))}
    for t in conn.execute("SELECT x, y, size FROM map_tokens WHERE map_id = ?", (map_id,)):
        for dx in range(t["size"] or 1):
            for dy in range(t["size"] or 1):
                used.add((int(round(t["x"])) + dx, int(round(t["y"])) + dy))
    sx, sy = d.get("start") or (-1, -1)
    rooms = [r for r in d["rooms"] if r["kind"] != "boss"]
    boss = [r for r in d["rooms"] if r["kind"] == "boss"]
    rnd.shuffle(rooms)
    papers = papers_for(level, rnd)
    # floor 5: the coordinates are in the head researcher's lab (the last paper), the rest on the way
    order = rooms + boss if level < 5 else rooms
    made = 0
    for i, (title, items) in enumerate(papers):
        if title in have:  # already down (place() can run again: it only adds the missing ones)
            continue
        pool = boss if (level == 5 and i == len(papers) - 1 and boss) else order
        if not pool:
            continue
        room = pool[i % len(pool)] if pool is order else pool[0]
        spots = [(x, y) for x, y in _cells_of(room["box"])
                 if m["terrain"].get(f"{x},{y}") not in M.BLOCKING and m["terrain"].get(f"{x},{y}") != "stairs"
                 and (x, y) not in used and (x, y) != (sx, sy)]
        if not spots:
            continue
        x0, y0, x1, y1 = room["box"]
        spots.sort(key=lambda p: (p[0] in (x0, x1) or p[1] in (y0, y1), rnd.random()))  # out in the room, where people walk
        x, y = spots[0]
        used.add((x, y))
        add_chest(conn, map_id, "papers", x, y, "", False, title, "placed", items, rnd.randrange(1, 2 ** 31))
        made += 1
    M._bump(conn, map_id)
    return made


def give_handout(conn, campaign_id, char_id, title, text, where):
    """The reader gets the paper as a handout (once per paper and reader)."""
    import json
    from .db import new_uid
    full = text + (f"\n\n(Found: {where}.)" if where else "")
    if conn.execute("SELECT 1 FROM handouts WHERE campaign_id = ? AND title = ? AND to_characters = ?",
                    (campaign_id, title, json.dumps([char_id]))).fetchone():
        return False
    conn.execute("INSERT INTO handouts (uid, campaign_id, title, body, image, to_characters, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (new_uid(), campaign_id, title, full, None, json.dumps([char_id]), now_iso(), now_iso()))
    return True
