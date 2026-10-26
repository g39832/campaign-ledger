# Campaign Ledger — D&D campaign tracker

A D&D 5e companion you run on your own computer. It covers character sheets, a morality and alignment tracker, a combat tracker, a battle map, 3D dice, a creature library, a campaign journal, and backups. Friends can join from their own phones or computers. Everything saves on its own as you work, and it's all still there after you close the browser, restart the app or turn off the computer.

---

## Starting it up

### The easy way (Windows)

1. Open the `Dnd Tracker` folder on your Desktop.
2. Double-click **`start.bat`**.
3. A black window opens and your browser goes to **http://127.0.0.1:5050**.

The first start takes a minute because it sets up Python packages. Later starts are quick.

**Leave the black window open while you play.** That window is the app. Closing it stops the app, but your data is already saved.

### Stopping it

Close the black window, or click in it and press `Ctrl + C`. Every change is saved as you make it, so there's nothing to save before you stop.

### Starting it from a terminal instead

```powershell
cd "$HOME\Desktop\Dnd Tracker"
.venv\Scripts\python run.py
```

Options:

| Command | What it does |
|---|---|
| `start.bat --port 8000` | Use a different port if 5050 is taken |
| `start.bat --lan` (or double-click `start-lan.bat`) | Lets friends' phones, tablets and computers join. See [Playing together](#playing-together) |
| `start.bat --no-browser` | Start without opening a browser tab |

> With `--lan`, other devices can reach the app, but they only get the **join page** until they enter your join code. Only this computer (or a device you gave a DM link) gets DM access.

### If it doesn't start

* **"python is not recognized"**: install Python 3.10 or newer from python.org and tick **"Add Python to PATH"** during setup. Then run `start.bat` again.
* **"address already in use"**: another program is using port 5050. Run `start.bat --port 5055`.
* **Broken setup**: delete the `.venv` folder and run `start.bat` again. It rebuilds the setup. Your data is in `data\`, not `.venv`, so you won't lose anything.

---

## What's in it

| Page | What you can do |
|---|---|
| **Dashboard** | See the party's HP, AC, passive Perception and conditions. Resume a running combat. Read the last session's summary, open quests and mysteries, and recent morality events. |
| **Characters** | Add PCs and NPCs. A character needs only a name to start. Archive characters you're not using. Only archived characters can be deleted for good. |
| **Character sheet** | Edit everything on the sheet. Ability modifiers, saves, skills (click the dot: proficient, then expertise), passive scores, proficiency bonus, initiative and spell DC/attack are worked out for you. "Homebrew adjustments" has overrides. The sheet also covers HP, temp HP, quick damage and heal, death saves, hit dice, exhaustion, conditions, attacks, equipment and coins, spells and spell slots, story, notes and a portrait. |
| **Combat** | Build an encounter from the party, the creature library, or a quick enemy (name, HP, AC and initiative modifier only). Enter or roll initiative. Turn order sorts itself, and the arrows let you change it by hand. Then use Next/Prev turn (keys **N** / **P**), damage, heal, temp HP, undo the last HP change, conditions with round-based durations, and a combat log. Each goblin has its own HP. Damage to a PC changes their character sheet too. |
| **Morality (Saints & Sinners)** | One −100 to +100 score for the whole party, starting at 0. Use the **−1** / **+1** buttons or type a number and press Enter (anything past ±100 is kept at the limit). It shows the level title and description (Absolute Sinner, Notorious Villain, Corrupted, Morally Questionable, Unproven, Virtuous, Hero, Saint, Paragon of Good) and whether the party is on the saintly or sinful side. Below it: the **benefits and drawbacks** of the current level, suggested **bonuses & penalties** for rolls (applied by you, not automatically), **examples** of how it plays out, and **dice rolls** you can click (they roll in the dice tray), plus a list of all levels. The Dashboard shows the score too. |
| **Journal** | Sessions, NPCs, locations, quests, factions, discoveries, decisions, mysteries, plot hooks, loot and notes. Entries can have a status, tags and links to characters, encounters or morality events. Search is at the top. |
| **Creatures** | Your monster library. **Monster Book** has 33 ready-made monsters (goblins, orcs, wolves, skeletons, ogres, a troll, dragons and more): search or filter by challenge rating, then **Add** one or **Add all shown**. Already-added ones are marked and never duplicated. **New creature** makes your own. Each stat block can be edited and has **Add to encounter** (pick a fight and how many). Enemies in a fight get a *copy* of the stats, so editing the library never changes a fight already set up. Monster Book stat blocks are based on the D&D 5e SRD 5.1 (CC BY 4.0). |
| **Campaigns** | Create, rename, switch between and archive campaigns. Archiving never deletes anything. Each campaign's characters, fights, notes and morality history are kept separate. |
| **Battle map** | See [Battle map](#battle-map). |
| **Players** | Who has joined, the join code, which map players see, and DM links for your other devices. |
| **Settings & Backups** | Dark/light theme, morality scale and thresholds, temp HP stacking, initiative tie rules, auto-sort, and which statuses "Next turn" skips. Backups and restore are also here. |

### How some of the rules work

* **Temp HP**: damage uses temp HP first. New temp HP keeps the higher value instead of stacking, which is the official rule. You can switch to stacking in Settings.
* **Dropping to 0 HP**: a PC becomes *Unconscious* and an enemy becomes *Defeated*. Healing a PC from 0 sets them back to *Fighting* and clears their death saves. The app notes massive damage in the log but doesn't kill anyone automatically. That's your call.
* **Effect durations**: an effect counts down once per round, at the start or end of a turn you choose. When it runs out, it's flagged for you to remove or keep. It's only removed by itself if you ticked "Remove automatically". Either way, it goes in the log.
* **Alignment**: scores go from −100 to +100 with 0 as neutral. A score of +34 or more is Lawful (or Good), −34 or less is Chaotic (or Evil), and anything in between is Neutral. You can change both numbers in Settings. A score is the starting score plus every recorded event, so editing or deleting an event changes the total by exactly that event's amount.
* **Undo HP**: undoes the most recent HP change in the encounter. If that combatant's HP has changed again since then (for example on the character sheet), it warns you first instead of overwriting the newer change.

---

## Fixing HP, and rests

**Fixing HP when something's wrong.** The character sheet, the combat panel and the player screen all have a **Fix HP** row (−5, −1, +1, +5), and you can type exact numbers anywhere HP is shown: current and max on the sheet, or "Set exact HP, max HP or temp HP" in combat. During a fight, a correction is written to the combat log and **Undo HP** reverses it. Undo warns you instead of overwriting anything that changed since.

**Short rest:** on the sheet, the Rest line has **Spend d10** (one button per hit-die size). It rolls the die plus Constitution, heals that much, and shows the roll in the dice tray. Set the character's hit dice first, like `5d10` (or `3d8 + 2d10` for a multiclass).

**Long rest:** the sheet's **Long rest** button rests one character. The Dashboard's **Long rest** rests the whole party (player characters only). A long rest restores:

* all HP, and temp HP ends
* half the character's hit dice (at least one)
* all spell slots
* one level of exhaustion
* death saves

Conditions are left for you to decide.

## Dice

Open the dice tray with the **Dice** button in the top bar, or press **D**.

* **Type an expression** and press Roll: `d20`, `1d20+5`, `2d6+3`, `4d8-1`, `d%` (d100), `2d20kh1` (keep highest), `2d20kl1` (keep lowest), `4d6dl1` (drop lowest), `3d6+1d4+2`. You can also click the d4–d100 buttons to build one (click twice for 2d6).
* **Click any number on a character sheet** to roll it: an ability modifier for an ability check, any saving throw or skill, initiative, death saves, spell attack, and the **Hit / Dmg / Crit** buttons on each attack. The app uses that character's real modifiers, proficiency and expertise.
* **Advantage and disadvantage:** pick it in the tray (it applies to the next d20 roll), or hold **Shift** while clicking for advantage and **Ctrl** for disadvantage.
* **Who sees it:** "Everyone", or "Hidden — only the DM". Players can pick everyone, "only the DM and me", or "only me". This is enforced by the server, not just hidden on screen.
* **Animation:** Normal, Fast, Dramatic (big dice across the whole screen), or Off. **Skip** jumps to the result and **Replay** shows the last roll again; neither rolls again. Clicking a roll in the history replays it. Off is the default if your computer is set to reduce motion.
* **On the battle map**, dice can tumble across the map itself ("Roll across the battle map" in the tray). This is only a picture on top; it never changes the map.

The server makes every roll and saves it to the history, which survives restarts. The animation is built backwards from that saved result, so the face that lands on top is always the real result. If a roll request is retried after a dropped connection, you get the same roll back, not a new one.

**In combat**, the panel for the selected combatant has a Rolls section:

* **Roll & set initiative** is the only roll that changes anything, and only the initiative.
* **All six saving throws** use an enemy's stat block, or a character's sheet.
* **To-hit and damage buttons** are read from an enemy's "Actions & attacks" text (e.g. `Scimitar. +4 to hit … (1d6 + 2) slashing`).

A damage roll never changes HP by itself. Its history entry gets an **Apply N to [selected combatant]** button, and a **Half** button for successful saves.

## Battle map

**Battle map** in the menu. Create a map with a grid size, and optionally link it to an encounter and upload a map image (PNG, JPEG or WebP).

* **Tools:**
  * **Move** drags tokens (drag empty space to pan).
  * **Pan**.
  * **Measure** is a ruler using the 5e rule that diagonals count as one square.
  * **Reveal / Hide** paint fog of war.
  * **Ping** shows everyone a spot with a ripple (double-click or double-tap works with any tool).
  * **Area** places spell areas: circles, cones, lines and cubes. There are quick sizes for Fireball, Burning Hands, Lightning Bolt and more, plus damage-type colours. The squares an area covers light up, and the sidebar lists who's inside. Drag an area to move it, turn cones and lines, or hide one from players.
  * **Terrain** paints walls, water, difficult ground, pits, doors, bushes, grass, sand, stone, wood, lava, ice, rubble, trees and furniture.
  * **Marker** drops a marker that starts hidden.
* **Ready-made maps:** on the Battle maps page, start from a tavern, cave, forest road, dungeon, river crossing, arena, ship deck or crypt.
* **Effects:** tokens show condition badges, floating damage and heal numbers, and a pulse on whoever's turn it is.
* **Zoom:** scroll wheel, pinch, or the + / − / fit buttons.
* **Grid:** square size, offset (to line up with an image), columns and rows, distance per square, colour and opacity, snapping, and background colour.
* **Monster attacks and spells, in plain words:** write one per line in the creature's **Actions & attacks** and **Spells** boxes, or in **Write attacks & spells** on the combat screen or the map (it can change every monster of that kind at once, and the library copy). Examples: `Bite 1d6`, `Claw +4 to hit 1d6+2`, `Fire bolt +5 2d10`, `Fireball 8d6`, `Healing word heal 1d4+2`, `Web: Restrained 10 rounds`, `Spread 1d20 must beat a 5`. Lines without dice show as notes.
* **Critical hits (house rule):** the d20 to hit always lands on screen first. On a natural 20 you get a **CRITICAL HIT!** banner and sound, then the damage rolls by itself with double the dice. This works on the map, the combat screen, the character sheet and the player screen.
* **At 0 HP (house rules):** monsters are **defeated** (a "Defeated!" banner and the token is crossed out). Heroes are **knocked prone** and make **death saves**: click **Roll death save** on the map, the combat screen, the sheet or the player's own screen, and the app counts it. 10 or more is a success, a natural 1 is two failures, a natural 20 brings them back with 1 HP; three successes is stable, three failures is dead. A hero still standing **right next to them on the map adds +2** (change it in **Settings → Combat**).
* **Everything rolls to hit (on by default):** every attack and harmful spell rolls a d20 plus its bonus against the target's AC; no bonus means +0. Heals and helpful spells just land. Turn it off in **Settings → Combat** to use saving throws (book rules).
* **Area attacks and spells you aim:** give an attack an **Area** on the sheet (e.g. `10 ft cone, range 20`), or use a spell whose notes say one (`15 ft cone`, `20 ft cube`, `20-foot radius`), or a monster line that does. On the map, click it: the area appears by the attacker pointing at the nearest enemy, with a dotted ring for its range. Drag to aim (cones and lines turn, circles and cubes move, never past the range), see who's caught, and **Confirm**. The damage rolls once; everyone in it rolls to hit against their own AC.
* **Run the fight from the map:** a turn bar above the map shows the round and whose turn it is, with **Roll initiative**, **Start combat**, **Prev** and **Next turn** (keys **P** and **N**).
* **Turns and cooldowns:** give a move a **Cooldown (turns)** on the sheet, or write it in the notes (`3 turn cool down`) or a monster line (`cooldown 2`). Once it's used in a fight it greys out as "recharging · ready in N turns" until that many of the user's turns have passed (it's an effect on them that removes itself; remove it under Conditions to use it early). Players can only attack on their own turn; the DM can still use a move out of turn by clicking it twice (reactions).
* **Combat ⇄ Map in one click:** a **Combat | Map** switch sits at the top of both screens (keys **C** and **M**; on a fight with no map yet, **Make map** builds one). Whoever you pick on one screen is already picked on the other. While a fight is running, the top menu's **Combat** and **Battle map** go straight to it; **All fights** and **Maps** lead back to the lists.
* **Fight right on the map:** click a token that's in the fight. The side panel shows its HP, AC, attacks and spells. Click an attack, then tap who it's aimed at: the app rolls to hit against their AC and, on a hit, rolls and deals the damage (doubled dice on a natural 20). Area and healing spells roll once; then tap each one they reach, with a "saved: half damage" box. Every hit has **Undo**, and there are Damage / Heal buttons for quick fixes.
* **Tokens:** "Add encounter" places a token for every combatant. You can also add characters one at a time. Each token has a label, type, size (Medium to Gargantuan), colour, "Hidden from players" and DM notes.
* **Tokens only store a position.** HP, conditions and turn order come from the encounter and the character sheets, so moving a token never changes combat, and combat changes show up on the map. The current turn's token is ringed in red, and the turn order with a **Next turn** button sits beside the map.
* **Show to players** makes this the map players see.

## Playing together

Your friends join from their own device and see the shared map, the turn order, their own character with roll buttons, the party's HP, and dice rolls as they happen.

1. **Start the app so other devices can reach it:** double-click `start-lan.bat`, or run `start.bat --lan`. The first time, Windows asks whether Python may use the network. Allow it on **Private networks**.
2. Open the **Players** page. It shows the join code and the addresses to send, e.g. `http://192.168.1.20:5050/join?code=XJ69RE`.
3. Friends open that address, enter their name and pick their character.
4. On a map, click **Show to players** (or choose the map on the Players page).

**What players can do with their own character:**

* Damage, Heal, Temp HP and Fix HP
* Spend or get back spell slots (tap the diamonds)
* Mark death saves at 0 HP
* Spend hit dice
* **Cast healing and buff spells on the party:** tap **Cast** on a spell (Cure Wounds, Bless, Shield of Faith…), then tap who gets it, either in the list or their token on the map. Tap more people for spells that reach several. Healing is rolled by the server. Spells that work against people (Bane, Hold Person) stay with the DM.
* **Disengage** in a fight: they're Disengaged until their turn ends and can drag their token away, even if you've locked token movement.

**Casting on the combat screen** works the same way: click **Cast** on a spell, then click who it's on. Healing spells roll first and then ask who gets it. Help spells list your side first; spells like Bane list the other side first. **Disengage** is a quick button under Conditions.

During a fight, their changes appear in your combat log with their name, and Undo HP works on them. You can turn each of these off in **Settings → What players can change**. The server enforces it, and they can never change max HP or anyone else's character.

**What players can and can't see.** Everything below is enforced on the server.

Players **can**:

* See the shared map, but not squares under fog. On uploaded images, those squares are blacked out in the picture itself.
* See tokens that aren't hidden or under fog, and hidden-from-players combatants never appear for them.
* See their own character, the party, and the turn order.
* Roll for their own character.
* Move their own token, unless you lock movement.

Players **can't**:

* See DM notes, hidden tokens or traps, or other people's private rolls.
* See any enemy's HP. Enemies only show as "bloodied" or "down".
* Change anything else.

**Friends who aren't on your Wi-Fi (free):** click **Go online** on the Players page. It starts a free Cloudflare quick tunnel and shows a link to send, together with the join code. The first time, install cloudflared once with `winget install --id Cloudflare.cloudflared`. Tailscale is the private alternative. **[ONLINE.md](ONLINE.md)** has the full guide.

**Quick encounters:** on the Combat page, one click sets up a fight: the party, Monster Book enemies and a matching ready-made map with everyone placed.

**Effects & sounds:** hits, heals, knock-outs, turn banners and natural 20s / 1s get flashes, floating numbers and short sounds. The sounds are made by the browser, so there's nothing to download. Each device can turn effects and sounds on or off in **Settings → Effects & sounds**, and players have a sound button in their top bar.

**Managing the table:**

* **New code** stops new people joining with the old code. Players already in stay in.
* **Remove** kicks a player.
* **Make DM link** lets you run the game from your own tablet. Anyone with that link is the DM, so keep it to yourself.

---

## Saving, and what the indicator in the top bar means

| Indicator | Meaning |
|---|---|
| ● All changes saved | The server has confirmed every change. |
| ● Saving… | A change is on its way. |
| ● **Not saved — retrying** | The server couldn't be reached. The app keeps your change and retries on its own (or click **Retry now**). |
| ● **Changed elsewhere** | Another tab or device changed the same field. You choose which version to keep, so nothing gets overwritten without you knowing. |
| ● **Not saved: …** | The value isn't allowed (e.g. level 99). Fix the field and it saves. |

The browser warns you if you try to close the tab while something is still unsaved.

Under the hood: all data lives in one SQLite database file. Each change is saved in a transaction, using a crash-safe mode, so a change the app has confirmed survives a crash or power cut. Every save tells the server what the value was before, and the server refuses a save if someone else changed that field in the meantime. Combat actions carry an ID, so a retried request never applies twice.

---

## Where your data lives

```
Dnd Tracker\
  data\
    dnd_tracker.sqlite3     <- your campaigns (the important file)
    uploads\                <- character portraits
    backups\                <- automatic snapshots of the database
```

To keep the data somewhere else (for example a synced folder), set the `DND_TRACKER_DATA` environment variable to that folder before starting the app.

---

## Backups and restoring

### Making a backup

In **Settings & Backups**:

* **Export "<campaign>"**: one campaign as a `.json` file, including portraits, battle maps (images, tokens, fog) and roll history. Player sessions are left out; players just join again.
* **Export everything**: all campaigns plus the creature library.
* **Database file**: a copy of the raw database.

Each campaign on the **Campaigns** page also has its own Export button.

Keep backups somewhere other than this computer, such as a USB stick or a cloud drive.

### Restoring from a `.json` backup

1. Go to **Settings & Backups → Restore from a backup** and choose the file.
2. The app checks the file first. It refuses files that are damaged or edited (the checksum won't match), from another app, or from a newer version.
3. You see what's in the file. For each campaign, choose **Import**, **Replace the existing one**, **Import as a copy**, or **Skip**. If you choose Replace, the app tells you exactly what will be swapped out.
4. Before importing anything, the app saves a snapshot of your current database in `data\backups\` (`before-import-….sqlite3`).

Campaigns that aren't in the backup are never touched.

### Automatic snapshots

Each day, the first time the app starts, it copies the database to `data\backups\daily-YYYYMMDD-….sqlite3`. It keeps the last 14.

When an update changes the database layout, the app first saves a copy to `data\backups\pre-migration-v1-to-v2-….sqlite3`, checks that the copy is intact, and only then upgrades. These copies aren't deleted automatically.

### Restoring a database snapshot

1. Stop the app.
2. In `data\`, rename `dnd_tracker.sqlite3` to `dnd_tracker.broken.sqlite3` so you keep it.
3. Delete `dnd_tracker.sqlite3-wal` and `dnd_tracker.sqlite3-shm` if they're there.
4. Copy the snapshot you want from `data\backups\` into `data\` and rename it to `dnd_tracker.sqlite3`.
5. Start the app.

---

## Running the tests

Double-click **`run-tests.bat`**, or run:

```powershell
.venv\Scripts\python -m pytest -q
```

The tests use a temporary database and never touch your real data. There are 192 of them. They cover:

* derived stats
* morality recalculation after editing, deleting and reversing events
* initiative and rounds
* independent enemy HP
* PC HP syncing with the sheet
* conditions and durations
* undo
* surviving a restart
* backing up and restoring into a separate test setup
* rejecting damaged backups
* conflicting edits and failed saves rolling back
* campaigns staying separate
* the dice parser, including rejected expressions, keep/drop, advantage and crits
* sheet rolls using the right modifiers
* duplicate roll requests
* rolls never changing game state
* DM/player permissions and roll visibility
* joining, kicking and DM links
* blocked cross-site and proxied requests
* battle map tokens, fog, hidden information and player moves
* server-side fog masking of map images
* backups that include maps and rolls
* the v1 → v2 database upgrade
* Saints & Sinners: ±1 steps, typed values, the −100/+100 limits, every level boundary, persistence and the database upgrade
* rests and hit dice
* HP corrections and player self-updates, including permission toggles
* no duplicate character tokens
* the Monster Book: every stat block valid and rollable, adding without duplicates, using added monsters in combat

The test helper sends requests the way the browser does (every write carries a request id), so tests catch problems that only show up from real button clicks.

---

## Project layout

```
run.py              starts the server (waitress)
start.bat           first-time setup + start
app/
  __init__.py       app factory, error handling
  db.py             SQLite connection, schema/migrations, snapshots
  rules.py          5e maths: modifiers, proficiency, skills, HP, initiative, alignment
  fields.py         field validation + the conflict-safe save
  campaigns.py  characters.py  morality.py  combat.py  creatures.py  journal.py  backup.py   (JSON API)
  dice.py           dice expression parser + roller (no eval)
  rolls.py          roll API, history and visibility
  auth.py           who is the DM / a player; the permission check every request passes
  play.py           joining, the player screen's data, player token moves and self-updates
  rest.py           short/long rests, hit dice, HP changes from the sheet
  maps.py           battle maps, tokens, terrain, fog, the player-safe map view
  pages.py          page routes
  templates/        HTML pages
  static/css/app.css, static/js/*.js, static/fonts (Alegreya, OFL), templates/_sprite.svg (Lucide icons, ISC)
  static/js/dice.js     3D dice renderer, tray and history
  static/js/mapview.js  map drawing and pan/zoom/drag, shared by the DM and player screens
tests/              automated tests
```

When the database layout changes in a future version, the app updates it by itself on startup (`db.py` → `MIGRATIONS`). Take a backup before updating anyway.

Packages: Flask (web app), waitress (server), Pillow (blacks out fogged areas of map images before they're sent to players), pytest (tests). `start.bat` installs them by itself whenever `requirements.txt` changes.

## Known limitations

* Players join with a code instead of accounts and passwords. That's fine for friends at your table, but don't put the app on the open internet without a tunnel or Tailscale.
* The app checks for updates every 1.5–3 seconds rather than pushing them live, so a player's move or roll shows up for others within a couple of seconds.
* Players can roll from their sheet and track HP, spell slots, death saves and hit dice. Everything else on the sheet is edited by the DM.
* Prev turn moves the turn back but doesn't undo effect countdowns (the log says so).
* Prev turn moves the turn marker back but doesn't wind effect durations back up. The log says so when you use it.
* There's no built-in spell or monster database. You type in your own stat blocks and spells, so you can use any official or homebrew content.
* Undo covers HP changes in combat. Other edits are just edited again by hand.
