"""The abandoned prison's enemies: ten homebrew stat blocks (not from the SRD), each with its own
way of fighting (app/ai.py reads TACTICS when the DM taps "Let it act"), its own picture (drawn
here with Pillow, so there are no image files to ship) and its own drops (app/loot.py DROPS).

They're in the Monster Book like any other monster, so the DM can also place and run them by hand.
Attack lines use the usual "Name. ... +N to hit ... Hit: X (NdS + M) type damage" form, and
", look laser" (or sparks, flames...) picks the animation on the battle map.
"""
from .statblock import _m

HOMEBREW = "Homebrew enemy from the abandoned prison."


def _boss(m, **extra):
    m.update(extra)
    return m


PRISON_MONSTERS = [
    # --- standard ------------------------------------------------------------------------------
    _m("Cybernetic Prison Guard", "Medium humanoid (cyborg), lawful neutral", "1", 27, 16, "30 ft.", (14, 14, 14, 10, 12, 10), [
        "Pulse Rifle. Ranged Weapon Attack: +4 to hit, range 60/180 ft. Hit: 7 (1d10 + 2) radiant damage, look laser.",
        "Shock Stock. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) lightning damage, look sparks.",
    ], traits=["Reinforced Armor. Plated body armor and a mirrored visor (AC included).",
               "Targeting Optics. Long-range shots don't have disadvantage.", HOMEBREW],
       senses="darkvision 60 ft. (optics), passive Perception 13", languages="Common"),
    _m("Riot Suppressor", "Medium humanoid (cyborg), lawful neutral", "2", 45, 18, "25 ft.", (16, 10, 16, 8, 11, 10), [
        "Stun Baton. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 8 (1d8 + 3) lightning damage, and the target must succeed on a DC 12 Constitution save or be Stunned 1 round, look sparks.",
        "Shield Bash. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 5 (1d4 + 3) bludgeoning damage, and the target is knocked Prone, look punch.",
    ], traits=["Riot Shield. A full-body energy shield (+2 AC, included).",
               "Hold the Line. It doesn't back away: it walks straight at the nearest enemy.", HOMEBREW],
       resistances="lightning", senses="passive Perception 10", languages="Common"),
    _m("Inmate Enforcer", "Medium humanoid (prisoner), chaotic evil", "1", 33, 13, "30 ft.", (16, 13, 14, 9, 10, 11), [
        "Multiattack. The enforcer makes two plasma shiv attacks.",
        "Plasma Shiv. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 6 (1d6 + 3) fire damage, look flames.",
        "Scrap Launcher. Ranged Weapon Attack: +3 to hit, range 30/90 ft. Hit: 5 (1d8 + 1) piercing damage, look arrow.",
    ], traits=["Smell Weakness. Advantage on attacks against a creature at half its hit points or fewer; it goes after the weakest.", HOMEBREW],
       senses="passive Perception 10", languages="Common, prison cant"),
    _m("Experimental Prisoner", "Medium monstrosity (mutant), chaotic neutral", "3", 58, 13, "40 ft.", (19, 14, 18, 6, 10, 7), [
        "Multiattack. The prisoner makes two mutant claw attacks.",
        "Mutant Claw. Melee Weapon Attack: +6 to hit, reach 10 ft. Hit: 9 (1d10 + 4) slashing damage, look slash.",
        "Bio-Shriek (Recharge 5–6). 15-ft. cone: each creature in it must make a DC 13 Constitution save, taking 14 (4d6) thunder damage and Frightened 1 round on a failure, or half as much damage on a success, look arcane.",
    ], traits=["Regeneration. Regains 5 hit points at the start of its turn if it has at least 1 hit point.",
               "Unstable Leap. Its long jump is 30 ft. with no running start.", HOMEBREW],
       senses="darkvision 60 ft., passive Perception 10", languages="understands Common but can't speak"),
    _m("Stealth Infiltrator", "Medium humanoid (assassin), neutral evil", "3", 39, 15, "35 ft.", (11, 18, 14, 13, 12, 10), [
        "Monoblade. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 8 (1d8 + 4) slashing damage, look slash.",
        "Needle Pistol. Ranged Weapon Attack: +6 to hit, range 40/120 ft. Hit: 7 (1d6 + 4) piercing damage, look arrow.",
    ], traits=["Cloaking Field. It starts a fight cloaked (Invisible). Its first attack from the cloak has advantage and deals an extra 10 (3d6) damage; then the cloak drops. It cloaks again on any turn it doesn't attack.",
               "Assassin's Eye. It hunts whoever stands farthest from their friends.", HOMEBREW],
       senses="passive Perception 14", languages="Common, two others"),
    # --- advanced ------------------------------------------------------------------------------
    _m("Security Drone", "Small construct, unaligned", "1", 22, 15, "fly 40 ft. (hover)", (6, 16, 12, 4, 12, 3), [
        "Twin Laser. Ranged Weapon Attack: +5 to hit, range 60/180 ft. Hit: 7 (2d4 + 3) radiant damage, look laser.",
    ], traits=["Flyby. It flies over pits and machines and never lets a foe stay next to it: it backs off, then fires.",
               "Construct. Doesn't breathe, eat or sleep.", HOMEBREW],
       immunities="poison, psychic", vulnerabilities="lightning", condition_immunities="poisoned, frightened",
       senses="darkvision 120 ft., passive Perception 13"),
    _m("Sentinel Unit", "Large construct, unaligned", "5", 95, 18, "25 ft.", (21, 9, 18, 3, 11, 1), [
        "Multiattack. The sentinel makes two hammer fist attacks.",
        "Hammer Fist. Melee Weapon Attack: +8 to hit, reach 10 ft. Hit: 14 (2d8 + 5) bludgeoning damage, look punch.",
        "Suppression Cannon (Recharge 5–6). 30-ft. line: each creature in it must make a DC 15 Dexterity save, taking 22 (4d10) force damage on a failure, or half as much on a success, look laser.",
    ], traits=["Armored Chassis. Resistant to bludgeoning, piercing and slashing damage from nonmagical attacks.", HOMEBREW],
       resistances="bludgeoning, piercing, and slashing from nonmagical attacks", immunities="poison, psychic",
       vulnerabilities="lightning", condition_immunities="charmed, frightened, poisoned", senses="darkvision 60 ft., passive Perception 10"),
    _m("Prototype Cyborg", "Medium humanoid (cyborg), neutral evil", "4", 76, 16, "30 ft.", (17, 15, 16, 12, 10, 8), [
        "Multiattack. The cyborg makes two attacks: arm blade if a foe is next to it, arm cannon if not.",
        "Arm Blade. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 10 (2d6 + 3) slashing damage, look slash.",
        "Arm Cannon. Ranged Weapon Attack: +6 to hit, range 60/180 ft. Hit: 11 (2d8 + 2) fire damage, look flames.",
        "Shock Grenade (Recharge 5–6). 10-ft. radius sphere within 60 ft.: each creature in it must make a DC 13 Dexterity save, taking 13 (3d8) lightning damage on a failure, or half as much on a success, look sparks.",
    ], traits=["Overclock. At half its hit points or fewer, it makes one more attack with Multiattack.", HOMEBREW],
       resistances="poison", senses="darkvision 60 ft., passive Perception 12", languages="Common"),
    _boss(_m("Prison Warden", "Medium humanoid (augmented), lawful evil", "7", 136, 18, "30 ft.", (16, 16, 18, 16, 14, 18), [
        "Multiattack. The warden makes two attacks: energy rifle at range, shock baton up close.",
        "Energy Rifle. Ranged Weapon Attack: +8 to hit, range 120/360 ft. Hit: 14 (2d10 + 3) radiant damage, look laser.",
        "Shock Baton. Melee Weapon Attack: +8 to hit, reach 5 ft. Hit: 10 (2d6 + 3) lightning damage, look sparks.",
        "Lockdown Grenade (Recharge 5–6). 15-ft. radius sphere within 90 ft.: each creature in it must make a DC 15 Dexterity save, taking 18 (4d8) force damage and Restrained 1 round on a failure, or half as much damage on a success, look arcane.",
    ], traits=["Command Armor. Powered plate with a personal shield generator (AC included).",
               "Keeps Its Distance. The warden backs away from melee and shoots.", HOMEBREW],
       resistances="lightning", condition_immunities="frightened", senses="darkvision 60 ft., passive Perception 15", languages="Common, three others"),
        boss=True, tagline="Warden of Block Omega", legendary_per_round=2, legendary_resistance=1, has_phase2=True,
        legendary="Command Override. The warden moves up to 15 ft. without provoking opportunity attacks.\n"
                  "Rifle Burst. Energy Rifle. Ranged Weapon Attack: +8 to hit, range 120/360 ft. Hit: 14 (2d10 + 3) radiant damage, look laser.",
        phase2="Overcharged Rifle. Ranged Weapon Attack: +9 to hit, range 120/360 ft. Hit: 22 (4d10) radiant damage, look laser.",
        loot="The Warden's access card (opens the Restricted vault), the warden's energy rifle, and a pouch of credit chips."),
    _m("Execution Unit", "Large construct, lawful evil", "8", 150, 19, "35 ft.", (22, 12, 20, 6, 12, 1), [
        "Multiattack. The unit makes two executioner blade attacks.",
        "Executioner Blade. Melee Weapon Attack: +9 to hit, reach 10 ft. Hit: 17 (2d10 + 6) slashing damage, look slash.",
        "Incinerator (Recharge 5–6). 20-ft. cone: each creature in it must make a DC 16 Dexterity save, taking 27 (6d8) fire damage on a failure, or half as much on a success, look flames.",
    ], traits=["Execution Protocol. It always hunts the most wounded foe, and deals an extra 11 (2d10) damage to a creature at half its hit points or fewer.",
               "Armored Chassis. Resistant to nonmagical weapon damage.", HOMEBREW],
       resistances="bludgeoning, piercing, and slashing from nonmagical attacks", immunities="fire, poison, psychic",
       vulnerabilities="lightning", condition_immunities="charmed, frightened, poisoned, stunned", senses="darkvision 120 ft., passive Perception 11"),
]
NAMES = [m["name"] for m in PRISON_MONSTERS]

# --- the laboratory (app/lab.py): five floors, the enemies get tougher the higher you climb -------
LAB_HOMEBREW = "Homebrew enemy from the laboratory."
# (2026-11-09, Grayson: the troops are weaker: 1 lower AC, and to hit only +1 or +2, +3 at most; the Head Researcher unchanged)
LAB_MONSTERS = [
    _m("Lab Assistant Drone", "Small construct, unaligned", "1/2", 16, 12, "fly 30 ft. (hover)", (6, 15, 12, 8, 12, 3), [
        "Sedative Needle. Melee Weapon Attack: +1 to hit, reach 5 ft. Hit: 5 (1d6 + 2) poison damage, look venom.",
        "Scalpel Laser. Ranged Weapon Attack: +1 to hit, range 30/90 ft. Hit: 4 (1d4 + 2) fire damage, look laser.",
    ], traits=["Hover. It flies over spills and grates and backs off before it fires.", LAB_HOMEBREW],
       immunities="poison, psychic", vulnerabilities="lightning", condition_immunities="poisoned", senses="darkvision 60 ft., passive Perception 11"),
    _m("Escaped Test Subject", "Medium monstrosity (mutant), chaotic neutral", "1", 30, 11, "40 ft.", (15, 14, 14, 5, 10, 6), [
        "Multiattack. The test subject makes two claw attacks.",
        "Claw. Melee Weapon Attack: +1 to hit, reach 5 ft. Hit: 5 (1d6 + 2) slashing damage, look slash.",
    ], traits=["Frenzied. It runs straight at the nearest creature it can see.", LAB_HOMEBREW],
       senses="darkvision 60 ft., passive Perception 10", languages="understands Common but can't speak"),
    _m("Hazmat Trooper", "Medium humanoid (security), lawful neutral", "2", 42, 15, "30 ft.", (14, 13, 14, 10, 12, 10), [
        "Acid Sprayer. Ranged Weapon Attack: +2 to hit, range 30/60 ft. Hit: 9 (2d6 + 2) acid damage, look venom.",
        "Shock Prod. Melee Weapon Attack: +2 to hit, reach 5 ft. Hit: 7 (1d8 + 3) lightning damage, look sparks.",
    ], traits=["Sealed Suit. A full hazmat suit with a respirator (AC included).", LAB_HOMEBREW],
       resistances="acid, poison", condition_immunities="poisoned", senses="passive Perception 13", languages="Common"),
    _m("Bio-Ooze", "Medium ooze, unaligned", "3", 60, 7, "20 ft., climb 20 ft.", (16, 6, 18, 1, 6, 1), [
        "Corrosive Pseudopod. Melee Weapon Attack: +2 to hit, reach 10 ft. Hit: 12 (2d8 + 3) acid damage, look venom.",
    ], traits=["Regrowing Mass. Regains 5 hit points at the start of its turn if it has at least 1 hit point.",
               "Amorphous. It can squeeze through a space as narrow as 1 inch.", LAB_HOMEBREW],
       resistances="acid", immunities="poison", condition_immunities="blinded, charmed, frightened, poisoned, prone",
       senses="blindsight 60 ft. (blind beyond this radius), passive Perception 8"),
    _m("Chimera Specimen", "Large monstrosity (experiment), chaotic evil", "5", 85, 14, "40 ft.", (19, 13, 17, 4, 12, 6), [
        "Multiattack. The specimen makes two attacks: one bite and one claw.",
        "Bite. Melee Weapon Attack: +3 to hit, reach 5 ft. Hit: 13 (2d8 + 4) piercing damage, look bite.",
        "Claw. Melee Weapon Attack: +3 to hit, reach 10 ft. Hit: 11 (2d6 + 4) slashing damage, look slash.",
        "Toxic Breath (Recharge 5–6). 15-ft. cone: each creature in it must make a DC 14 Constitution save, taking 22 (4d10) poison damage on a failure, or half as much on a success, look venom.",
    ], traits=["Spliced Hunter. It goes after the most wounded creature it can see.", LAB_HOMEBREW],
       resistances="poison", senses="darkvision 60 ft., passive Perception 13"),
    _boss(_m("Head Researcher", "Medium humanoid (augmented), neutral evil", "8", 150, 17, "30 ft.", (12, 16, 16, 20, 14, 14), [
        "Multiattack. The researcher makes two attacks: plasma caster at range, gene lash up close.",
        "Plasma Caster. Ranged Weapon Attack: +8 to hit, range 60/180 ft. Hit: 14 (2d10 + 3) fire damage, look flames.",
        "Gene Lash. Melee Weapon Attack: +8 to hit, reach 10 ft. Hit: 13 (2d8 + 4) necrotic damage, look venom.",
        "Mutagen Flask (Recharge 5–6). 15-ft. radius sphere within 60 ft.: each creature in it must make a DC 15 Constitution save, taking 27 (6d8) poison damage and Poisoned 1 round on a failure, or half as much damage on a success, look venom.",
    ], traits=["Lab Coat Barrier. A personal shield generator sewn into the coat (AC included).",
               "Keeps Its Distance. The researcher backs away from melee and fires.", LAB_HOMEBREW],
       resistances="poison, acid", condition_immunities="poisoned", senses="darkvision 60 ft., passive Perception 14", languages="Common, four others"),
        boss=True, tagline="Head of Project Chimera", legendary_per_round=2, legendary_resistance=1, has_phase2=True,
        legendary="Adrenal Shot. The researcher moves up to 15 ft. without provoking opportunity attacks.\n"
                  "Plasma Burst. Plasma Caster. Ranged Weapon Attack: +8 to hit, range 60/180 ft. Hit: 14 (2d10 + 3) fire damage, look flames.",
        phase2="Self-Mutation. Mutant Claws. Melee Weapon Attack: +9 to hit, reach 10 ft. Hit: 20 (3d10 + 4) slashing damage, look slash.",
        loot="The key to the safe behind it (one rare magic item) and a pouch of lab credits."),
    # The Director (2026-11-15): head of Project Chimera, the lab's final fight. Scaled for Lux, Moni,
    # Yamato and Gnocchi (levels 4-5) WITH Zephyra (level 15) at their side: lots of HP and two legendary
    # resistances so Zephyra's big spells don't end it in a round, and (Grayson, 2026-11-15) harder-hitting attacks: +7, DC 15.
    # About 70 damage a round if everything lands.
    _boss(_m("The Director", "Medium humanoid (augmented), neutral evil", "10", 300, 15, "30 ft.", (12, 16, 18, 20, 16, 18), [
        "Multiattack. The Director makes two attacks: Graft Claw up close or Gene Ray at range, in any mix; Mind Splice can take the place of one.",
        "Graft Claw. Melee Weapon Attack: +7 to hit, reach 10 ft. Hit: 17 (3d8 + 4) slashing damage, look slash.",
        "Gene Ray. Ranged Spell Attack: +7 to hit, range 60 ft. Hit: 19 (3d10 + 3) necrotic damage, look venom.",
        "Mind Splice (Recharge 5–6). Ranged Spell Attack: +7 to hit, range 60 ft. Hit: 22 (4d8 + 4) psychic damage, and the target must succeed on a DC 15 Wisdom save or be Stunned 1 round, look arcane.",
        "Splice Spray (Recharge 5–6). 15-ft. cone: each creature in it must make a DC 15 Constitution save, taking 28 (8d6) poison damage and Poisoned 1 round on a failure, or half as much damage on a success, look venom.",
    ], traits=["Unseen Face. A mirrored mask and a hood: nobody in the lab has seen the Director's face.",
               "Adaptive Hide. Grafted skin hardens against poison and acid (resistances included).",
               "Escape Plan (DM). Once the Director drops to 40 HP or less, it can use its reaction to slip away through a "
               "hidden lift behind the safe. The DM decides whether it gets away.",
               "Interest in Stone (DM only, don't say it out loud). The Director watches any creature that fights with "
               "stone or earth very closely, and would rather capture it than kill it: it never aims Splice Spray at it.",
               LAB_HOMEBREW],
       resistances="poison, acid", condition_immunities="poisoned, frightened",
       senses="darkvision 60 ft., passive Perception 16", languages="Common, five others"),
        boss=True, tagline="Director of Project Chimera", legendary_per_round=2, legendary_resistance=2, has_phase2=True,
        legendary="Shift. The Director moves up to 15 ft. without provoking opportunity attacks.\n"
                  "Lash. Graft Claw. Melee Weapon Attack: +7 to hit, reach 10 ft. Hit: 17 (3d8 + 4) slashing damage, look slash.",
        phase2="Final Graft. Chimera Maw. Melee Weapon Attack: +8 to hit, reach 10 ft. Hit: 26 (4d10 + 4) piercing damage, look bite.",
        loot="The key to the Director's safe (one rare magic item), a pouch of lab credits, and a sealed folder stamped "
             "E SERIES — CONFIDENTIAL (the DM decides when it's opened)."),
]
LAB_NAMES = [m["name"] for m in LAB_MONSTERS]


# ---- the missile silo (2026-11-16): Steven Voss's machines, tougher than the lab's -------------------
SILO_HOMEBREW = "Homebrew enemy from the missile silo."
SILO_MONSTERS = [
    _m("Voss Sentry Drone", "Small construct, unaligned", "1", 24, 14, "fly 40 ft. (hover)", (6, 16, 12, 6, 12, 3), [
        "Rotor Laser. Ranged Weapon Attack: +4 to hit, range 60/120 ft. Hit: 7 (1d10 + 2) radiant damage, look laser.",
        "Ram. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) bludgeoning damage, look punch.",
    ], traits=["Hover. It flies, keeps its distance and fires.", "Voss Optics. Steven sees what it sees.", SILO_HOMEBREW],
       immunities="poison, psychic", vulnerabilities="lightning", condition_immunities="poisoned, charmed, frightened",
       senses="darkvision 60 ft., passive Perception 12"),
    _m("Silo Guard Automaton", "Medium construct, lawful neutral", "3", 52, 16, "30 ft.", (17, 10, 16, 6, 10, 3), [
        "Multiattack. The automaton makes two riot fist attacks, or fires its shoulder gun once.",
        "Riot Fist. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 9 (2d6 + 2) bludgeoning damage, look punch.",
        "Shoulder Gun. Ranged Weapon Attack: +4 to hit, range 60/180 ft. Hit: 10 (2d8 + 1) piercing damage, look laser.",
    ], traits=["Steel Shell. Riveted plate over a concrete-grey frame (AC included).",
               "Post Orders. It doesn't leave the room it guards until someone it can see does.", SILO_HOMEBREW],
       immunities="poison, psychic", condition_immunities="poisoned, charmed, frightened",
       senses="darkvision 60 ft., passive Perception 11", languages="understands Common"),
    _m("Voss Loyalist Engineer", "Medium humanoid (human), lawful evil", "2", 40, 14, "30 ft.", (11, 14, 13, 16, 12, 10), [
        "Arc Welder. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 9 (2d6 + 2) fire damage, look flames.",
        "Rivet Gun. Ranged Weapon Attack: +4 to hit, range 40/120 ft. Hit: 7 (1d10 + 2) piercing damage, look arrow.",
    ], traits=["Loyal to Voss. Worked on IRONCLAD for years; won't surrender while Steven is in the silo.",
               "Field Repair. Once per fight, a machine (or itself) within 5 ft. regains 2d8 + 3 hit points (DM).", SILO_HOMEBREW],
       senses="passive Perception 13", languages="Common, Gnomish"),
    _m("Point-Defense Turret", "Medium construct, unaligned", "3", 44, 17, "0 ft.", (10, 14, 16, 3, 12, 1), [
        "Twin Cannon. Ranged Weapon Attack: +5 to hit, range 80/240 ft. Hit: 11 (2d8 + 2) piercing damage, look laser.",
    ], traits=["Bolted Down. It can't move, and it can't be pushed or knocked prone.",
               "Tracking Lock. It fires at whoever last hurt it, or the nearest creature it can see.", SILO_HOMEBREW],
       immunities="poison, psychic", condition_immunities="poisoned, charmed, frightened, prone",
       senses="blindsight 60 ft., passive Perception 13"),
    _m("Ironclad Walker", "Large construct, unaligned", "5", 98, 17, "30 ft.", (20, 9, 18, 3, 10, 1), [
        "Multiattack. The walker makes two piston fist attacks.",
        "Piston Fist. Melee Weapon Attack: +5 to hit, reach 10 ft. Hit: 13 (2d8 + 4) bludgeoning damage, look punch.",
        "Missile Pod (Recharge 5–6). 10-ft. radius sphere within 60 ft.: each creature in it must make a DC 14 Dexterity save, taking 18 (4d8) fire damage on a failure, or half as much on a success, look flames.",
    ], traits=["Project IRONCLAD. An early model of the giant in the launch bay: same frame, no face.", SILO_HOMEBREW],
       immunities="poison, psychic", condition_immunities="poisoned, charmed, frightened",
       senses="darkvision 60 ft., passive Perception 10"),
    # The silo's last fight (2026-11-16, Grayson): Steven rebuilt his son Harlan as a giant robot. It fights
    # with Harlan's own moves made huge (Smash, Stunning Smash, Earth Shattter, shield bash, Rally) plus
    # rockets and a core beam. Scaled like the Director (Lux, Moni, Yamato and Gnocchi at levels 4-5 with
    # Zephyra at 15): lots of HP, +7 to hit, two legendary resistances, a nastier phase 2.
    # Steven himself does NOT fight: app/silo.py puts him on his gantry as a story token.
    _boss(_m("Ironclad Harlan", "Huge construct, lawful neutral", "12", 380, 17, "30 ft.", (24, 9, 22, 6, 12, 10), [
        "Iron Smash: +7 to hit, 2d10+6 bludgeoning damage, reach 10 ft, look punch",
        "Stunning Smash: +7 to hit, 3d10+6 bludgeoning damage, Prone 1 rounds, reach 10 ft, 2 turn cooldown, look punch",
        "Earth Shattter: +7 to hit, 4d10 bludgeoning damage, Prone 1 rounds, 30 ft radius, 4 turn cooldown, look quake",
        "Rocket Barrage: +7 to hit, 3d8 fire damage, 15 ft radius, range 90, 2 turn cooldown, look flames",
        "Core Beam: +7 to hit, 6d8 radiant damage, 60 ft line, 5 turn cooldown, look laser",
    ], traits=["Built in His Image. A twenty-foot steel giant with Harlan Voss's face cast in iron, Harlan's shield "
               "welded to its left arm, and every move Harlan had, copied from memory and made huge.",
               "Steven's Last Project. Project IRONCLAD, unit H. It guards the launch bay until the missiles fly.",
               "Voice Box (DM). Now and then it speaks in a recording of Harlan's voice: \"Dad? Is it time yet?\"",
               "Doesn't Hurt Steven. It never aims at Steven Voss, and it steps between him and anyone chasing him.",
               "Rally (Harlan's). Self-repair: now and then it heals instead of attacking.",
               SILO_HOMEBREW],
       resistances="lightning, thunder; bludgeoning, piercing and slashing from nonmagical attacks",
       immunities="poison, psychic", condition_immunities="poisoned, charmed, frightened, exhaustion",
       senses="darkvision 120 ft., passive Perception 14", languages="understands Common; speaks only in Harlan's recorded voice"),
        boss=True, tagline="Steven rebuilt his son. In steel.", legendary_per_round=2, legendary_resistance=2, has_phase2=True,
        spells="Rally: heal 3d10+10, 4 turn cooldown, look holy\nLaunch Drones: summon 2 Voss Sentry Drone, 4 at once, 3 turn cooldown",
        legendary="Shield Bash: +7 to hit, 2d8+4 bludgeoning damage, Prone 1 rounds, 1 turn cooldown, look punch",
        phase2="Grief Engine: +8 to hit, 4d10+6 bludgeoning damage, Shocked 1 rounds, push 20 ft, reach 15 ft, look punch\n"
               "Fault Line: +8 to hit, 6d10 bludgeoning damage, Prone 1 rounds, 40 ft radius, 3 turn cooldown, look quake\n"
               "Steam Vent: +8 to hit, 4d8 fire damage, Shocked 1 rounds, push 15 ft, 20 ft cone, range 0, 2 turn cooldown, look flames",
        loot="Harlan's shield, still welded to the arm (the DM decides if it comes free), and the robot's core: Project IRONCLAD unit H."),
]
SILO_NAMES = [m["name"] for m in SILO_MONSTERS]

# How each one fights (app/ai.py):
#   target: nearest | weakest (lowest HP share) | isolated (farthest from its friends)
#   style:  melee (walk up and hit) | ranged (stay at range, back off from melee) | kite (fly, never stay next to a foe) | adaptive
TACTICS = {
    "Cybernetic Prison Guard": {"target": "nearest", "style": "ranged", "keep": 4},
    "Riot Suppressor": {"target": "nearest", "style": "melee"},
    "Inmate Enforcer": {"target": "weakest", "style": "melee", "adv_bloodied": True},
    "Experimental Prisoner": {"target": "nearest", "style": "melee", "regen": 5},
    "Stealth Infiltrator": {"target": "isolated", "style": "melee", "cloak": True, "sneak": "3d6"},
    "Security Drone": {"target": "nearest", "style": "kite", "fly": True, "keep": 4},
    "Sentinel Unit": {"target": "nearest", "style": "melee"},
    "Prototype Cyborg": {"target": "nearest", "style": "adaptive", "overclock": True},
    "Prison Warden": {"target": "nearest", "style": "ranged", "keep": 5},
    "Execution Unit": {"target": "weakest", "style": "melee", "bonus_bloodied": "2d10"},
    # the laboratory
    "Lab Assistant Drone": {"target": "nearest", "style": "kite", "fly": True, "keep": 3},
    "Escaped Test Subject": {"target": "nearest", "style": "melee"},
    "Hazmat Trooper": {"target": "nearest", "style": "ranged", "keep": 3},
    "Bio-Ooze": {"target": "nearest", "style": "melee", "regen": 5},
    "Chimera Specimen": {"target": "weakest", "style": "melee"},
    "Head Researcher": {"target": "nearest", "style": "ranged", "keep": 4},
    "The Director": {"target": "nearest", "style": "adaptive"},
    # the missile silo
    "Voss Sentry Drone": {"target": "nearest", "style": "kite", "fly": True, "keep": 4},
    "Silo Guard Automaton": {"target": "nearest", "style": "melee"},
    "Voss Loyalist Engineer": {"target": "nearest", "style": "ranged", "keep": 3},
    "Point-Defense Turret": {"target": "nearest", "style": "ranged", "keep": 0},
    "Ironclad Walker": {"target": "nearest", "style": "melee"},
    "Ironclad Harlan": {"target": "nearest", "style": "melee"},
}


# ---- pictures --------------------------------------------------------------------------------------
# One recognisable silhouette each, drawn on a dark disc with a red emergency rim (tokens are round).

def draw(name, size=256):
    from PIL import Image, ImageDraw
    S = size / 100.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(pts):
        return [(x * S, y * S) for x, y in pts]

    def box(x0, y0, x1, y1, fill, outline=None, r=0):
        if r:
            d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill, outline=outline, width=max(1, int(S * 1.5)))
        else:
            d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, outline=outline, width=max(1, int(S * 1.5)))

    def circ(cx, cy, r, fill, outline=None, w=1.5):
        d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill, outline=outline, width=max(1, int(S * w)))

    def line(pts, fill, w):
        d.line(P(pts), fill=fill, width=max(1, int(w * S)))

    bg = {"Prison Warden": (40, 20, 24), "Execution Unit": (36, 16, 14), "Experimental Prisoner": (24, 34, 22),
          "Stealth Infiltrator": (18, 20, 34), "Head Researcher": (20, 34, 30), "The Director": (14, 12, 18), "Chimera Specimen": (34, 26, 20),
          "Bio-Ooze": (18, 32, 20), "Ironclad Harlan": (30, 26, 22), "Voss Loyalist Engineer": (34, 30, 24)}.get(name, (24, 27, 33))
    # lab enemies get a toxic-green rim, silo ones hazard amber, prison ones the red emergency rim
    rim = (70, 220, 110, 255) if name in LAB_NAMES else (240, 170, 30, 255) if name in SILO_NAMES else (200, 40, 40, 255)
    circ(50, 50, 48, bg + (255,), rim, 3)
    steel, dark, red, cyan = (150, 160, 172, 255), (60, 66, 76, 255), (235, 50, 45, 255), (90, 220, 255, 255)
    if name == "Cybernetic Prison Guard":
        box(30, 52, 70, 88, (70, 82, 98, 255), steel, 6)           # armored torso
        circ(50, 34, 15, (80, 92, 108, 255), steel)                # helmet
        box(38, 30, 62, 38, cyan, None, 3)                         # visor
        box(62, 58, 92, 64, dark, steel, 2)                        # rifle
        line([(88, 61), (95, 61)], red, 2)
    elif name == "Riot Suppressor":
        circ(50, 32, 14, (70, 74, 82, 255), steel)
        box(40, 29, 60, 35, (255, 190, 60, 255), None, 2)
        box(28, 48, 72, 90, (64, 70, 80, 255), steel, 6)
        box(14, 42, 40, 92, (120, 200, 255, 110), cyan, 6)         # energy riot shield
        line([(76, 46), (90, 30)], steel, 5)                        # baton
        circ(91, 28, 4, (255, 240, 120, 255))
    elif name == "Inmate Enforcer":
        box(30, 50, 70, 90, (230, 120, 30, 255), (120, 60, 10, 255), 6)   # orange jumpsuit
        line([(34, 70), (66, 70)], (40, 40, 40, 255), 2)
        circ(50, 34, 14, (196, 150, 120, 255), (90, 60, 40, 255))
        line([(40, 30), (48, 33)], (60, 30, 20, 255), 2)
        line([(72, 60), (88, 44)], (255, 120, 40, 255), 4)          # plasma shiv
        circ(88, 44, 4, (255, 200, 80, 255))
    elif name == "Experimental Prisoner":
        d.polygon(P([(22, 92), (28, 50), (40, 40), (60, 40), (72, 50), (80, 92)]), fill=(110, 140, 90, 255), outline=(60, 90, 50, 255))
        circ(50, 32, 13, (140, 170, 110, 255), (70, 100, 60, 255))
        circ(44, 30, 3, (220, 255, 80, 255)); circ(56, 30, 3, (220, 255, 80, 255))
        for x in (30, 70):
            line([(x, 52), (x + (-14 if x < 50 else 14), 66), (x + (-10 if x < 50 else 10), 78)], (200, 230, 160, 255), 4)  # claws
        circ(60, 62, 6, (150, 255, 120, 160))  # glowing veins
        circ(42, 74, 4, (150, 255, 120, 160))
    elif name == "Stealth Infiltrator":
        d.polygon(P([(30, 92), (36, 50), (50, 42), (64, 50), (70, 92)]), fill=(30, 34, 52, 200), outline=(120, 140, 255, 180))
        circ(50, 32, 12, (36, 40, 60, 210), (120, 140, 255, 200))
        box(40, 29, 60, 33, (160, 120, 255, 255), None, 2)
        line([(66, 56), (88, 30)], (200, 220, 255, 255), 3)          # monoblade
        for i in range(5):
            line([(18 + i * 4, 40 + i * 9), (24 + i * 4, 40 + i * 9)], (120, 140, 255, 120), 1)  # shimmer
    elif name == "Security Drone":
        box(30, 40, 70, 62, (90, 100, 112, 255), steel, 10)
        circ(50, 51, 8, (20, 20, 24, 255), steel)
        circ(50, 51, 4, red)                                     # the eye
        for x in (22, 78):
            line([(x - 12, 34), (x + 12, 34)], steel, 3)          # rotors
            line([(x, 34), (x, 44)], steel, 3)
        line([(44, 62), (40, 74)], steel, 2); line([(56, 62), (60, 74)], steel, 2)
    elif name == "Sentinel Unit":
        box(22, 36, 78, 82, (96, 104, 110, 255), steel, 4)         # huge chassis
        box(36, 18, 64, 36, (80, 88, 96, 255), steel, 3)
        box(40, 24, 60, 30, red, None, 2)
        box(8, 40, 22, 74, dark, steel, 3); box(78, 40, 92, 74, dark, steel, 3)   # fists
        box(30, 82, 44, 94, dark); box(56, 82, 70, 94, dark)
        line([(30, 50), (70, 50)], (255, 200, 40, 255), 2)        # hazard stripe
    elif name == "Prototype Cyborg":
        box(32, 50, 66, 90, (110, 96, 92, 255), steel, 6)
        circ(48, 33, 13, (200, 160, 140, 255), steel)
        d.pieslice([35 * S, 20 * S, 61 * S, 46 * S], 270, 90, fill=(140, 150, 160, 255))  # half machine face
        circ(54, 31, 3, red)
        box(66, 54, 92, 64, (90, 96, 104, 255), steel, 3)          # arm cannon
        circ(92, 59, 4, (255, 140, 40, 255))
        line([(32, 60), (14, 80)], (220, 230, 240, 255), 3)        # arm blade
    elif name == "Prison Warden":
        box(28, 50, 72, 92, (50, 36, 44, 255), (220, 180, 90, 255), 6)   # long coat
        circ(50, 32, 14, (190, 150, 130, 255), (90, 60, 50, 255))
        box(34, 16, 66, 22, (30, 30, 36, 255)); box(40, 10, 60, 18, (30, 30, 36, 255))   # officer's cap
        circ(50, 14, 3, (240, 200, 80, 255))
        line([(40, 56), (40, 64)], (240, 200, 80, 255), 2); line([(60, 56), (60, 64)], (240, 200, 80, 255), 2)
        box(60, 62, 96, 70, dark, steel, 2)                         # energy rifle
        line([(92, 66), (98, 66)], cyan, 3)
    elif name == "Execution Unit":
        d.polygon(P([(20, 90), (26, 40), (50, 28), (74, 40), (80, 90)]), fill=(70, 50, 46, 255), outline=(200, 80, 40, 255))
        box(38, 16, 62, 34, (50, 40, 40, 255), (200, 80, 40, 255), 3)
        line([(41, 25), (59, 25)], red, 4)                         # one red slit
        d.polygon(P([(80, 40), (98, 20), (94, 50), (82, 58)]), fill=(210, 220, 230, 255))   # the blade
        circ(50, 58, 7, (255, 110, 40, 255))
    elif name == "Lab Assistant Drone":
        circ(50, 48, 18, (220, 226, 232, 255), steel)                # white medical shell
        box(40, 44, 60, 50, (40, 44, 52, 255), None, 3)
        circ(50, 47, 3, (90, 220, 255, 255))
        line([(40, 62), (32, 78)], steel, 2); line([(60, 62), (70, 74)], steel, 2)   # arms
        line([(70, 74), (78, 80)], (140, 255, 140, 255), 2)          # needle
        line([(26, 28), (74, 28)], steel, 3); line([(50, 28), (50, 31)], steel, 3)   # rotor
    elif name == "Escaped Test Subject":
        box(32, 50, 68, 90, (225, 232, 238, 255), (150, 160, 170, 255), 6)   # torn hospital gown
        line([(36, 80), (44, 74), (52, 82)], (150, 160, 170, 255), 2)
        circ(50, 34, 13, (170, 160, 150, 255), (90, 80, 70, 255))
        circ(45, 32, 2.5, (255, 80, 60, 255)); circ(55, 32, 2.5, (255, 80, 60, 255))
        box(34, 62, 40, 66, (255, 200, 60, 255))                       # wristband tag
        for x in (26, 74):
            line([(x, 56), (x + (-8 if x < 50 else 8), 72)], (200, 190, 180, 255), 4)
    elif name == "Hazmat Trooper":
        box(30, 48, 70, 90, (240, 200, 40, 255), (140, 110, 20, 255), 6)   # yellow hazmat suit
        circ(50, 32, 15, (240, 200, 40, 255), (140, 110, 20, 255))
        box(39, 27, 61, 37, (40, 60, 70, 255), cyan, 4)                # visor
        circ(50, 43, 4, dark)                                          # respirator
        box(64, 58, 92, 64, dark, steel, 2)                            # sprayer
        circ(92, 61, 4, (140, 255, 90, 255))
    elif name == "Bio-Ooze":
        d.polygon(P([(14, 86), (20, 60), (34, 44), (50, 36), (68, 42), (82, 58), (88, 86)]), fill=(90, 210, 80, 220), outline=(40, 140, 40, 255))
        for cx, cy, r in ((40, 62, 5), (60, 56, 4), (52, 74, 6), (70, 72, 3)):
            circ(cx, cy, r, (200, 255, 160, 170))                      # bubbles
        circ(44, 50, 3, (20, 40, 20, 255)); circ(58, 48, 3, (20, 40, 20, 255))
    elif name == "Chimera Specimen":
        d.polygon(P([(14, 88), (20, 54), (38, 40), (64, 40), (82, 54), (88, 88)]), fill=(120, 90, 70, 255), outline=(70, 50, 40, 255))
        circ(38, 34, 13, (150, 110, 80, 255), (80, 60, 40, 255))      # lion head
        circ(66, 30, 10, (90, 120, 80, 255), (50, 80, 40, 255))        # lizard head
        circ(34, 32, 2.5, (255, 220, 60, 255)); circ(68, 28, 2.5, (255, 60, 60, 255))
        line([(48, 70), (52, 60), (56, 70), (60, 60)], (230, 230, 230, 255), 2)   # stitches
        line([(82, 66), (96, 56)], (90, 120, 80, 255), 5)              # tail
    elif name == "Head Researcher":
        box(28, 50, 72, 92, (236, 240, 244, 255), (150, 160, 170, 255), 6)   # lab coat
        line([(50, 52), (50, 92)], (150, 160, 170, 255), 2)
        circ(50, 32, 14, (200, 165, 140, 255), (100, 70, 50, 255))
        d.pieslice([36 * S, 16 * S, 64 * S, 40 * S], 180, 360, fill=(200, 200, 205, 255))  # grey hair
        box(38, 28, 62, 34, (90, 220, 255, 220), (40, 60, 70, 255), 2)       # goggles
        box(62, 60, 70, 76, (140, 255, 90, 230), (40, 140, 40, 255), 2)       # mutagen vial
        line([(22, 62), (8, 76)], (140, 255, 90, 255), 4)              # gene lash
    elif name == "The Director":
        d.polygon(P([(18, 94), (26, 52), (50, 44), (74, 52), (82, 94)]), fill=(28, 26, 34, 255), outline=(70, 66, 80, 255))  # long dark coat
        d.pieslice([28 * S, 12 * S, 72 * S, 60 * S], 180, 360, fill=(36, 32, 44, 255))       # hood
        box(30, 34, 70, 50, (36, 32, 44, 255))
        d.ellipse([36 * S, 22 * S, 64 * S, 50 * S], fill=(190, 200, 210, 255), outline=(90, 100, 110, 255), width=max(1, int(S * 1.5)))  # mirrored mask
        line([(40, 30), (60, 44)], (120, 130, 140, 255), 2)                                  # a scratch across it
        line([(44, 26), (62, 38)], (120, 130, 140, 255), 1.5)
        circ(44, 36, 2.5, (140, 255, 90, 255)); circ(56, 36, 2.5, (140, 255, 90, 255))     # green eyes behind it
        line([(74, 62), (90, 74), (94, 66)], (140, 255, 90, 255), 4)                         # grafted claw
        box(46, 60, 54, 66, (140, 255, 90, 230), (40, 140, 40, 255), 2)                      # Chimera badge
    elif name == "Voss Sentry Drone":
        box(34, 40, 66, 60, (70, 74, 70, 255), (240, 170, 30, 255), 8)   # olive drone body with amber trim
        circ(50, 50, 9, (20, 20, 24, 255), steel)
        circ(50, 50, 5, (255, 190, 60, 255))                              # Voss's goggle lens
        for x in (24, 76):
            circ(x, 34, 11, None, steel, 2)                                # rotor rings
            line([(x, 38), (x + (10 if x < 50 else -10), 44)], steel, 3)
        line([(46, 60), (42, 72)], (90, 220, 255, 255), 3)                # laser
    elif name == "Silo Guard Automaton":
        box(30, 46, 70, 88, (128, 128, 120, 255), (60, 60, 56, 255), 4)  # concrete-grey frame
        for yy in (54, 70):
            for xx in (36, 64):
                circ(xx, yy, 2, (60, 60, 56, 255))                         # rivets
        box(36, 20, 64, 44, (150, 150, 140, 255), (60, 60, 56, 255), 4)
        box(40, 28, 60, 34, (240, 170, 30, 255), None, 2)                  # amber visor slit
        box(70, 40, 84, 50, dark, steel, 2)                                # shoulder gun
        line([(84, 45), (94, 45)], steel, 3)
        box(16, 56, 30, 70, dark, steel, 3)                                # fist
    elif name == "Voss Loyalist Engineer":
        box(30, 50, 70, 92, (90, 70, 40, 255), (50, 38, 20, 255), 6)     # work overalls
        box(30, 60, 70, 66, (240, 170, 30, 255))                           # reflective band
        circ(50, 34, 14, (205, 165, 135, 255), (100, 70, 50, 255))
        d.pieslice([34 * S, 14 * S, 66 * S, 40 * S], 180, 360, fill=(240, 200, 40, 255))   # hard hat
        box(38, 30, 62, 36, (40, 40, 44, 255), None, 2)                    # welding goggles
        circ(44, 33, 3, (255, 190, 60, 255)); circ(56, 33, 3, (255, 190, 60, 255))
        line([(70, 70), (88, 56)], steel, 4)                               # arc welder
        circ(90, 54, 4, (120, 220, 255, 255))
    elif name == "Point-Defense Turret":
        box(26, 66, 74, 90, (80, 80, 76, 255), steel, 4)                   # base bolted to the floor
        circ(50, 54, 20, (110, 112, 108, 255), steel)
        box(60, 42, 94, 48, dark, steel, 2); box(60, 56, 94, 62, dark, steel, 2)   # twin barrels
        circ(50, 54, 6, (255, 70, 50, 255))
        for xx in (30, 70):
            circ(xx, 84, 2, (40, 40, 40, 255))
    elif name == "Ironclad Walker":
        box(24, 34, 76, 78, (96, 92, 84, 255), steel, 6)                   # boxy hull
        box(32, 22, 68, 36, (80, 76, 70, 255), steel, 3)
        box(40, 26, 60, 32, (240, 170, 30, 255), None, 2)
        box(8, 40, 24, 70, dark, steel, 3); box(76, 40, 92, 70, dark, steel, 3)    # piston arms
        box(30, 78, 44, 94, dark); box(56, 78, 70, 94, dark)
        for i in range(4):
            box(28 + i * 12, 70, 34 + i * 12, 76, (240, 170, 30, 255) if i % 2 == 0 else (30, 30, 30, 255))
        box(62, 14, 74, 22, (150, 60, 40, 255), steel, 2)                  # missile pod
    elif name == "Ironclad Harlan":
        # a giant iron head and shoulders: Harlan's face cast in steel, his shield on the left arm
        box(14, 60, 86, 96, (92, 86, 78, 255), steel, 8)                   # shoulders
        for xx in (22, 78):
            circ(xx, 70, 3, (50, 46, 42, 255))
        box(30, 14, 70, 64, (140, 132, 120, 255), (70, 64, 58, 255), 12)  # the iron face
        box(30, 14, 70, 24, (90, 84, 76, 255), None, 8)                    # brow plate / cast hair
        line([(36, 31), (46, 33)], (50, 46, 42, 255), 3); line([(54, 33), (64, 31)], (50, 46, 42, 255), 3)   # brows
        box(37, 35, 46, 40, (255, 150, 40, 255), None, 2); box(54, 35, 63, 40, (255, 150, 40, 255), None, 2)  # glowing eyes
        line([(50, 40), (48, 48), (52, 48)], (90, 84, 76, 255), 2)          # nose
        line([(42, 54), (58, 54)], (60, 56, 50, 255), 3)                     # set jaw
        for yy in (44, 52, 60):
            circ(31, yy, 1.5, (60, 56, 50, 255)); circ(69, yy, 1.5, (60, 56, 50, 255))   # weld seams
        d.polygon(P([(2, 62), (22, 56), (24, 92), (8, 98), (2, 90)]), fill=(120, 60, 40, 255), outline=(220, 180, 90, 255))  # Harlan's shield
        circ(13, 76, 5, (220, 180, 90, 255))
        box(46, 66, 54, 74, (255, 150, 40, 230), (120, 60, 20, 255), 2)     # glowing core
    else:
        circ(50, 50, 20, steel)
    return img


def portrait_file(upload_dir, name):
    """Make the picture once (data/uploads/prison-<name>.png) and return its file name."""
    import os
    fn = ("lab-" if name in LAB_NAMES else "silo-" if name in SILO_NAMES else "prison-") + name.lower().replace(" ", "-") + ".png"
    path = os.path.join(upload_dir, fn)
    if not os.path.exists(path):
        draw(name).save(path, "PNG", optimize=True)
    return fn
