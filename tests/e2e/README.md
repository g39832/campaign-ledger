# Browser tests

These click through the app in real browsers: Chrome, Firefox and WebKit (Safari's engine), at
phone, tablet and laptop sizes. They always run on a **copy** of your data. `run.py` copies
`data/` into `tests/e2e/.tmp`, starts a test server on port 5077 and stops it afterwards. Your
real game is never touched.

## One-time setup

Playwright isn't part of the app, so it gets its own Python environment:

```powershell
cd "$HOME\Desktop\Dnd Tracker"
py -m venv tests\e2e\.venv
tests\e2e\.venv\Scripts\python -m pip install -r tests\e2e\requirements.txt
tests\e2e\.venv\Scripts\python -m playwright install chromium firefox webkit
```

The Chrome runs use your installed Google Chrome (`channel="chrome"`).

## Running

```powershell
# one test, in Chrome
tests\e2e\.venv\Scripts\python tests\e2e\run.py e2e_players.py

# a full game on phones, laptops and tablets mixed, in all three browsers
tests\e2e\.venv\Scripts\python tests\e2e\run.py e2e_players.py e2e_moves.py --engine all --devices mixed

# everything
tests\e2e\.venv\Scripts\python tests\e2e\run.py --all
```

Each run prints one line, for example
`e2e_players.py [chromium/mixed]: 65 passed, 0 failed`. Add `E2E_VERBOSE=1` to see every check.
Screenshots go to `tests/e2e/shots`.

Phones join the test server over your Wi-Fi address, which is worked out each run (see
`common.py`). Set `E2E_LAN_IP` to override it.

## What's here

| Script | What it checks |
|---|---|
| `e2e_players.py` | A full round played only from players' devices: moves panel, movement, Dash/End turn, off-turn private rolls, Parry, Yamato's clones, pings, leave and rejoin |
| `e2e_moves.py` | Every move on every hero's sheet, used from their own screen |
| `e2e_clonespot.py` | Picking where Yamato's clones appear (phone, laptop, DM tablet, fog, hidden traps) |
| `e2e_dicecolors.py` | Dice colors from the phone and the sheet; others see them |
| `e2e_monrows.py` | The monster attack/spell form (every library and book line reads the same) |
| `e2e_bosses.py` / `e2e_monicons.py` | The Bosses section; monster pictures in the library, combat and on tokens |
| `e2e_rollwho.py` | The "who is rolling" title |
| `e2e_turns.py`, `e2e_reach.py`, `e2e_zone.py`, `e2e_edges.py`, `e2e_accuracy.py`, `e2e_phone_cone.py`, `e2e_fx.py` | Turn and movement rules, melee reach, Spirit Guardians, edge cases, roll accuracy, cone aiming, attack effects |
| `e2e_round.py`, `e2e_yamato.py`, `e2e_combat.py`, `e2e_dm_rules.py`, `e2e_dm_tablet.py`, `e2e_landscape.py` | The DM side: a whole round, Yamato's clone and Parry, the combat screen, DM rules, tablet and landscape layouts |
| `e2e_all.py` | A sweep of every page |
| `e2e_sheetfold.py`, `e2e_skills.py` | The sheet's folding sections and typed-in skills |
| `e2e_reload.py` | Open pages reload themselves after an update (starts its own server) |
| `e2e_online_dead.py` | The Players page notices a dead online link (about 100 seconds) |

The tests expect the real campaign's characters (Lux Fedelis, Moni Easter, Yamato, Gnocchi) and
creatures to exist, because they run on a copy of your data.
