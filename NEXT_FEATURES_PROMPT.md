# Hand-off prompt: Campaign Ledger, the next features

Paste everything below into a new coding session (Claude Code or similar) opened in
`~/Desktop/Dnd Tracker`. It explains the project and exactly how to build each feature.
Features already done are marked **DONE**; continue with the first one that isn't.

---

## The project

**Campaign Ledger** is Grayson's D&D 5e campaign tracker. It runs on his Windows PC, and friends
join from phones, tablets and laptops. Public repo: github.com/g39832/campaign-ledger.

- **Stack:** Python 3.11, Flask, waitress, stdlib sqlite3, Pillow. Vanilla JS, no build step. Venv in `.venv`.
- **Run it:** `start-lan.bat` serves on 0.0.0.0:5050. Restart it after any Python or template change.
  Templates are cached, and JS/CSS are cache-busted with `?v=N` in every template. Bump N in
  *all* of `app/templates/*.html` when JS or CSS changes. Open pages reload themselves after a
  server restart (they compare `/api/join/build`).
- **Data:** `data/dnd_tracker.sqlite3`, plus `data/uploads` and `data/backups`. Never touch real
  data in tests. Schema migrations live in `app/db.py` (`SCHEMA_VERSION` and `MIGRATIONS`). Each one
  adds columns only, and a pre-migration backup is taken automatically.
- **Auth:** the DM is a request from this computer (or a DM-link cookie). Players join with a code
  (`/join`) and get a player cookie. `app/auth.py guard()` lets players reach only
  `PLAYER_PREFIXES` (`/play`, `/api/play/`, `/api/rolls`, `/api/uploads/`, `/join`, `/api/join`).
- **Saving:** pages autosave field by field: `PATCH {changes: {field: {from, to}}}` (compare and
  set), and every write carries an `op_id` so it isn't applied twice (`claim_op`).
- **Key files:**
  - `app/combat.py`: encounters and combatants.
  - `app/spells.py`: the spell engine (`cast()`, zones, summons, take-back/undo).
  - `app/rolls.py`: dice rolls and their visibility; `roll_dict()` adds each roll's dice colors.
  - `app/maps.py`: the battle map, tokens, fog and pings; `player_view()` is what players may see.
  - `app/play.py`: everything a player does from `/play`.
  - `app/movement.py`: turn rules, speed and actions.
  - `app/online.py`: the Cloudflare quick tunnel. It runs detached and is found again through
    cloudflared's metrics at `127.0.0.1:20241-20245/quicktunnel`.
  - `app/creatures.py`: the monster library (boss flag, picture).
  - JS: `core.js` (helpers `h()`, `api()`, `Binder`, the cast panel, the monster attack form
    `attackRows`, the dice color picker), `map.js` and `mapview.js` (DM map, canvas),
    `play.js` (player screen), `combat.js`, `dice.js` (3D dice, "who is rolling" title),
    `sheet.js`, `creatures.js`.
- **House rules:** no spell slots (cooldowns only). Two actions per turn (Action Surge adds two).
  Players move only on their turn, within their speed. Off-turn rolls are private. Friendly fire
  is on. Yamato's clones are run by his player. Monsters' attacks are text lines
  ("Claw: +4 to hit, 1d6+2 slashing damage") read by `L.parseAttack` / `L.attackLines`.
- **Testing:**
  - Code tests: `.venv\Scripts\python -m pytest -q` (about 370 tests, 2 minutes).
  - Browser tests: Playwright, in `tests/e2e` (see feature 3). They run against a *copy* of the
    real data on port 5077/5078, in Chrome, Firefox and WebKit, at phone, tablet and laptop sizes.
  - Grayson wants every change clicked through in real browsers before it's pushed.
- **Rules for working here:**
  - Never credit Claude/AI as author or co-author in commits or PRs (no Co-Authored-By lines).
  - Changes must only *add*: keep old behavior working.
  - Back up real data (`data/backups/before-*.sqlite3`) before changing it.
  - Don't rewrite UTF-8 files with PowerShell 5.1 content cmdlets; use Python.
  - Push to GitHub when Grayson asks, then restart the server.

---

## Features to build (in this order)

### 1. The online link: notice when it dies, one click for a new one
**Problem:** Cloudflare quick tunnels sometimes drop and never come back. cloudflared keeps
logging `"Register tunnel error from server side"`, the hostname stops resolving, and the app
still shows the dead link as "on".

**Build:**
- In `app/online.py status()`, check the tunnel's health:
  - Read `http://127.0.0.1:<metrics port>/metrics` and parse `cloudflared_tunnel_ha_connections`.
    If it's 0 for more than about 60 s, call the tunnel `"broken"`.
  - Optionally, also tail `data/cloudflared.log` for "Register tunnel error" lines newer than
    the last "Registered tunnel connection".
  - Return `{running, url, broken: true, error: "The online link stopped working — get a new one"}`.
- `POST /api/online/start` when the tunnel is broken: stop the dead tunnel (the existing
  `stop_left_running()` kills it by its metrics port), then start a fresh one.
- On the Players page (find the Go online UI by searching templates/JS for `/api/online`):
  show a red "The online link stopped working" banner with a **Get a new link** button.
- Tests: monkeypatch the metrics reader. In `tests/conftest.py` there's an autouse fixture
  that sets `online.METRICS_PORTS = range(0)` so tests never touch a real tunnel. Keep it.

### 3. Save the browser tests in the project
- Move the Playwright scripts into `tests/e2e/` (players, moves, clones, dice colors, monster
  rows, bosses, monster icons, rollwho, reach, zone, turns, etc.). Make paths relative: no
  hard-coded scratch folders.
- Read the LAN address at run time (pick the Wi-Fi IPv4 from `socket` or `ipconfig`), never
  hard-code it.
- Add `tests/e2e/run.py` and `tests/e2e/README.md`:
  - **Copy:** copy `data/dnd_tracker.sqlite3` (sqlite backup API, read-only source) and
    `data/uploads` into a temp folder.
  - **Start:** start `run.py --port 5077 --no-browser --lan` with `DND_TRACKER_DATA=<temp>`.
  - **Run:** run the chosen script(s) with `ENGINE=chromium|firefox|webkit` and
    `DEVICES=phones|laptops|tablets|mixed`.
  - **Stop:** stop the server, including its process tree. The venv `python.exe` is a launcher
    with a child process, so kill whatever listens on the port.
- Playwright goes in a separate venv or as an optional dev requirement, never in the app's
  `requirements.txt`.
- pytest must not collect `tests/e2e`. Add `collect_ignore = ["e2e"]` in `tests/conftest.py`
  or name the files without the `test_` prefix.

### 4. QR code for joining
- On the Players page, show a QR code for the join link:
  - the online link if it's running and healthy,
  - else the LAN link (`http://<current LAN IP>:5050/join`).
  - Add a "Show code big" button for the table.
- Generate it server-side with Pillow (no new dependency) or a small pure-Python QR encoder
  vendored into `app/qr.py`, served as PNG from `GET /api/join-qr?url=` (DM only).
  Alternatively, a tiny vendored JS QR encoder (MIT) under `app/static/js/`. No CDN: the app
  must work offline.
- Include the join code in the URL (`/join?code=XXXXXX`) and make `/join` prefill the code
  from the query string.

### 5. Instant updates (instead of polling every 1.5 s)
- Add a server-sent events endpoint `GET /api/events?campaign=<id>` (also allowed for players:
  add it to `PLAYER_PREFIXES` as `/api/play/events`, or put it under `/api/play/`). It streams
  `event: change\ndata: {"kind": "map"|"encounter"|"rolls"|"party", "id": ...}`.
- **Server side:** a small in-memory pub/sub in a new `app/events.py`:
  - `publish(campaign_id, kind, id)` puts the event on every subscriber's
    `queue.Queue(maxsize=100)`.
  - Call it wherever `rev` is bumped (`_bump()` in `app/maps.py`, the encounter
    `rev = rev + 1` updates, `save_roll`, character HP changes). Search for `rev = rev + 1` and
    `_bump(`.
  - Waitress has 8 threads, so each stream must not hold a thread forever. Either raise
    `threads` in `run.py` to about 32, or send a keep-alive comment every 15 s and end streams
    after about 5 minutes (EventSource reconnects by itself).
- **Client side:** in `core.js`, an `L.live(onChange)` helper using `EventSource`.
  - `play.js`, `map.js`, `combat.js` and `dice.js` call their existing `load()` / `refresh()` /
    `poll()` when an event arrives.
  - **Keep the 1.5 s polling as a fallback**, slowed to every 10 s while the stream is
    connected, so nothing breaks if SSE fails behind the Cloudflare tunnel.
- Test: two browsers. A move on one shows on the other in under 500 ms.

### 7. Player handouts
- **The DM pushes a handout:** an uploaded picture and/or a text note, with a title, to
  everyone or to chosen players.
- **New table** (a migration): `handouts(id, uid, campaign_id, title, body, image, to_players
  JSON list or NULL for everyone, created_at, dismissed JSON)`.
- **DM UI:** a "Handouts" panel on the Players page with a form, image upload (reuse the
  portrait upload pattern in `app/creatures.py`), Send, and a list of what's been sent.
- **Player UI:** a handout pops up as a big card over `/play` (title, picture, text, Close),
  and stays in a "Handouts" list on their screen.
- Players may load the handout image: extend `uploads()` in `app/characters.py`, as was done
  for creature pictures.
- Include handouts in backups (`app/backup.py`: export rows and files).

### 6. Boss extras
For creatures with `boss = 1` (already on the creatures table and copied into combatants'
`statblock`):
- **Boss health bar:** in a fight with a boss, a wide bar across the top of everyone's screen
  (DM map, Combat, and players' `/play`) with the boss's name and health. Players see a bar
  without numbers, matching the existing "bloodied/down" rule (players never see enemy HP or AC).
- **Legendary actions:** a new creature field `legendary` (text lines, same format as attacks)
  and `legendary_per_round` (int, default 3). In the fight, at the end of each other
  creature's turn, the DM's panel offers "Legendary action (2 left)" buttons for the boss.
  The count resets at the start of the boss's turn. Store the count in the combatant's
  `moved` JSON or its own column.
- **Phase 2:** a creature field `phase2` (text lines). When the boss drops to half HP, show a
  "Phase 2!" banner (`FX.banner`), and from then on its moves include the phase 2 attacks.
- **Legendary resistance:** `legendary_resistance` (int, for example 3). When the boss fails a
  save in the spell engine, the DM gets "Use legendary resistance (2 left)?", which turns the
  failure into a success. Hook this in `app/spells.py` where saves are resolved.
- Add these fields to the creature form (`creatures.js`). They show only when Boss is ticked.

---

## After each feature
1. Run `pytest -q`. Every test must pass.
2. Write or extend a browser test in `tests/e2e` and run it in chromium, firefox and webkit,
   on phone and laptop sizes.
3. Commit with a plain message (no AI credit), push to GitHub, and restart the server (end
   the `start-lan.bat` process, then start it again).
4. Mark the feature **DONE** in this file.
