"""A starter Monster Book of common creatures.

Stat blocks are based on the System Reference Document 5.1 by Wizards of the
Coast, available under the Creative Commons Attribution 4.0 International
License (https://creativecommons.org/licenses/by/4.0/). Adding one copies it
into the campaign's creature library, where the DM can edit it freely.

Attack lines follow the "Name. ... +N to hit ... Hit: X (NdS + M)" format, so
the combat screen turns them into roll buttons.
"""

ATTRIBUTION = ("Monster stat blocks based on the System Reference Document 5.1 by Wizards of the Coast LLC, "
               "licensed under CC BY 4.0.")


def _m(name, creature_type, cr, hp, ac, speed, abilities, attacks, traits="", senses="", languages="",
       resistances="", immunities="", vulnerabilities="", condition_immunities=""):
    keys = ("str", "dex", "con", "int", "wis", "cha")
    ab = dict(zip(keys, abilities))
    return {
        "name": name, "creature_type": creature_type, "cr": cr, "max_hp": hp, "ac": ac, "speed": speed,
        "initiative_mod": (ab["dex"] - 10) // 2, "abilities": ab, "attacks": "\n".join(attacks),
        "traits": "\n".join(traits) if isinstance(traits, (list, tuple)) else traits,
        "senses": senses, "languages": languages, "resistances": resistances, "immunities": immunities,
        "vulnerabilities": vulnerabilities, "condition_immunities": condition_immunities,
    }


MONSTERS = [
    # --- humanoids ---------------------------------------------------------------
    _m("Bandit", "Medium humanoid (any race), any non-lawful", "1/8", 11, 12, "30 ft.", (11, 12, 12, 10, 10, 10), [
        "Scimitar. Melee Weapon Attack: +3 to hit, reach 5 ft. Hit: 4 (1d6 + 1) slashing damage.",
        "Light Crossbow. Ranged Weapon Attack: +3 to hit, range 80/320 ft. Hit: 5 (1d8 + 1) piercing damage.",
    ], senses="passive Perception 10", languages="any one language (usually Common)"),
    _m("Bandit Captain", "Medium humanoid (any race), any non-lawful", "2", 65, 15, "30 ft.", (15, 16, 14, 14, 11, 14), [
        "Multiattack. The captain makes three melee attacks: two with its scimitar and one with its dagger.",
        "Scimitar. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 6 (1d6 + 3) slashing damage.",
        "Dagger. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 20/60 ft. Hit: 5 (1d4 + 3) piercing damage.",
    ], traits=["Parry (reaction). Adds 2 to its AC against one melee attack that would hit it, if it can see the attacker and is wielding a melee weapon."],
       senses="passive Perception 10", languages="any two languages"),
    _m("Thug", "Medium humanoid (any race), any non-good", "1/2", 32, 11, "30 ft.", (15, 11, 14, 10, 10, 11), [
        "Multiattack. The thug makes two melee attacks.",
        "Mace. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) bludgeoning damage.",
        "Heavy Crossbow. Ranged Weapon Attack: +2 to hit, range 100/400 ft. Hit: 5 (1d10) piercing damage.",
    ], traits=["Pack Tactics. Advantage on attack rolls against a creature if an ally is within 5 ft. of it and isn't incapacitated."],
       senses="passive Perception 10", languages="any one language (usually Common)"),
    _m("Guard", "Medium humanoid (any race), any alignment", "1/8", 11, 16, "30 ft.", (13, 12, 12, 10, 11, 10), [
        "Spear. Melee or Ranged Weapon Attack: +3 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d6 + 1) piercing damage, or 5 (1d8 + 1) if used with two hands.",
    ], senses="passive Perception 12", languages="any one language (usually Common)"),
    _m("Veteran", "Medium humanoid (any race), any alignment", "3", 58, 17, "30 ft.", (16, 13, 14, 10, 11, 10), [
        "Multiattack. The veteran makes two longsword attacks. If it has a shortsword drawn, it can also make a shortsword attack.",
        "Longsword. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 7 (1d8 + 3) slashing damage, or 8 (1d10 + 3) if used with two hands.",
        "Shortsword. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 6 (1d6 + 3) piercing damage.",
        "Heavy Crossbow. Ranged Weapon Attack: +3 to hit, range 100/400 ft. Hit: 6 (1d10 + 1) piercing damage.",
    ], senses="passive Perception 12", languages="any one language (usually Common)"),
    _m("Cultist", "Medium humanoid (any race), any non-good", "1/8", 9, 12, "30 ft.", (11, 12, 10, 10, 11, 10), [
        "Scimitar. Melee Weapon Attack: +3 to hit, reach 5 ft. Hit: 4 (1d6 + 1) slashing damage.",
    ], traits=["Dark Devotion. Advantage on saving throws against being charmed or frightened."],
       senses="passive Perception 10", languages="any one language (usually Common)"),
    _m("Cult Fanatic", "Medium humanoid (any race), any non-good", "2", 33, 13, "30 ft.", (11, 14, 12, 10, 13, 14), [
        "Multiattack. The fanatic makes two melee attacks.",
        "Dagger. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d4 + 2) piercing damage.",
    ], traits=["Dark Devotion. Advantage on saving throws against being charmed or frightened.",
               "Spellcasting. 4th-level caster, Wisdom (spell save DC 11, +3 to hit). Cantrips: light, sacred flame, thaumaturgy. 1st (4 slots): command, inflict wounds, shield of faith. 2nd (3 slots): hold person, spiritual weapon."],
       senses="passive Perception 11", languages="any one language (usually Common)"),
    _m("Priest", "Medium humanoid (any race), any alignment", "2", 27, 13, "30 ft.", (10, 10, 12, 13, 16, 13), [
        "Mace. Melee Weapon Attack: +2 to hit, reach 5 ft. Hit: 3 (1d6) bludgeoning damage.",
    ], traits=["Divine Eminence. As a bonus action, expend a spell slot to deal an extra 10 (3d6) radiant damage on a melee hit.",
               "Spellcasting. 5th-level caster, Wisdom (spell save DC 13, +5 to hit). Cantrips: light, sacred flame, thaumaturgy. 1st (4 slots): cure wounds, guiding bolt, sanctuary. 2nd (3 slots): lesser restoration, spiritual weapon. 3rd (2 slots): dispel magic, spirit guardians."],
       senses="passive Perception 13", languages="any two languages"),
    _m("Mage", "Medium humanoid (any race), any alignment", "6", 40, 12, "30 ft.", (9, 14, 11, 17, 12, 11), [
        "Dagger. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 20/60 ft. Hit: 4 (1d4 + 2) piercing damage.",
    ], traits=["AC 15 with mage armor.",
               "Spellcasting. 9th-level caster, Intelligence (spell save DC 14, +6 to hit). Cantrips: fire bolt, light, mage hand, prestidigitation. 1st (4 slots): detect magic, mage armor, magic missile, shield. 2nd (3 slots): misty step, suggestion. 3rd (3 slots): counterspell, fireball, fly. 4th (3 slots): greater invisibility, ice storm. 5th (1 slot): cone of cold."],
       senses="passive Perception 11", languages="any four languages"),
    # --- goblinoids & friends ------------------------------------------------------------
    _m("Goblin", "Small humanoid (goblinoid), neutral evil", "1/4", 7, 15, "30 ft.", (8, 14, 10, 10, 8, 8), [
        "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) slashing damage.",
        "Shortbow. Ranged Weapon Attack: +4 to hit, range 80/320 ft. Hit: 5 (1d6 + 2) piercing damage.",
    ], traits=["Nimble Escape. Can take the Disengage or Hide action as a bonus action on each of its turns."],
       senses="darkvision 60 ft., passive Perception 9", languages="Common, Goblin"),
    _m("Goblin Boss", "Small humanoid (goblinoid), neutral evil", "1", 21, 17, "30 ft.", (10, 14, 10, 10, 8, 10), [
        "Multiattack. The goblin boss makes two scimitar attacks. The second has disadvantage.",
        "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) slashing damage.",
        "Javelin. Melee or Ranged Weapon Attack: +2 to hit, reach 5 ft. or range 30/120 ft. Hit: 3 (1d6) piercing damage.",
    ], traits=["Nimble Escape. Can take the Disengage or Hide action as a bonus action on each of its turns.",
               "Redirect Attack (reaction). When targeted by an attack, swap places with a goblin within 5 ft.; the goblin becomes the target."],
       senses="darkvision 60 ft., passive Perception 9", languages="Common, Goblin"),
    _m("Hobgoblin", "Medium humanoid (goblinoid), lawful evil", "1/2", 11, 18, "30 ft.", (13, 12, 12, 10, 10, 9), [
        "Longsword. Melee Weapon Attack: +3 to hit, reach 5 ft. Hit: 5 (1d8 + 1) slashing damage, or 6 (1d10 + 1) if used with two hands.",
        "Longbow. Ranged Weapon Attack: +3 to hit, range 150/600 ft. Hit: 5 (1d8 + 1) piercing damage.",
    ], traits=["Martial Advantage. Once per turn, deals an extra 7 (2d6) damage to a creature it hits if an ally is within 5 ft. of that creature."],
       senses="darkvision 60 ft., passive Perception 10", languages="Common, Goblin"),
    _m("Bugbear", "Medium humanoid (goblinoid), chaotic evil", "1", 27, 16, "30 ft.", (15, 14, 13, 8, 11, 9), [
        "Morningstar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 11 (2d8 + 2) piercing damage.",
        "Javelin. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 30/120 ft. Hit: 9 (2d6 + 2) piercing damage in melee or 5 (1d6 + 2) at range.",
    ], traits=["Brute. A melee weapon deals one extra die of its damage when the bugbear hits with it (included).",
               "Surprise Attack. If it surprises a creature and hits it in the first round, the target takes an extra 7 (2d6) damage."],
       senses="darkvision 60 ft., passive Perception 10", languages="Common, Goblin"),
    _m("Kobold", "Small humanoid (kobold), lawful evil", "1/8", 5, 12, "30 ft.", (7, 15, 9, 8, 7, 8), [
        "Dagger. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 4 (1d4 + 2) piercing damage.",
        "Sling. Ranged Weapon Attack: +4 to hit, range 30/120 ft. Hit: 4 (1d4 + 2) bludgeoning damage.",
    ], traits=["Sunlight Sensitivity. Disadvantage on attack rolls and sight-based Perception checks in sunlight.",
               "Pack Tactics. Advantage on attack rolls against a creature if an ally is within 5 ft. of it and isn't incapacitated."],
       senses="darkvision 60 ft., passive Perception 8", languages="Common, Draconic"),
    _m("Orc", "Medium humanoid (orc), chaotic evil", "1/2", 15, 13, "30 ft.", (16, 12, 16, 7, 11, 10), [
        "Greataxe. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 9 (1d12 + 3) slashing damage.",
        "Javelin. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 30/120 ft. Hit: 6 (1d6 + 3) piercing damage.",
    ], traits=["Aggressive. As a bonus action, can move up to its speed toward a hostile creature it can see."],
       senses="darkvision 60 ft., passive Perception 10", languages="Common, Orc"),
    _m("Gnoll", "Medium humanoid (gnoll), chaotic evil", "1/2", 22, 15, "30 ft.", (14, 12, 11, 6, 10, 7), [
        "Bite. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 4 (1d4 + 2) piercing damage.",
        "Spear. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 20/60 ft. Hit: 5 (1d6 + 2) piercing damage.",
        "Longbow. Ranged Weapon Attack: +3 to hit, range 150/600 ft. Hit: 5 (1d8 + 1) piercing damage.",
    ], traits=["Rampage. When it reduces a creature to 0 HP with a melee attack, it can move up to half its speed and make a bite attack as a bonus action."],
       senses="darkvision 60 ft., passive Perception 10", languages="Gnoll"),
    # --- undead -------------------------------------------------------------------
    _m("Skeleton", "Medium undead, lawful evil", "1/4", 13, 13, "30 ft.", (10, 14, 15, 6, 8, 5), [
        "Shortsword. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) piercing damage.",
        "Shortbow. Ranged Weapon Attack: +4 to hit, range 80/320 ft. Hit: 5 (1d6 + 2) piercing damage.",
    ], vulnerabilities="bludgeoning", immunities="poison", condition_immunities="exhaustion, poisoned",
       senses="darkvision 60 ft., passive Perception 9", languages="understands the languages it knew in life but can't speak"),
    _m("Zombie", "Medium undead, neutral evil", "1/4", 22, 8, "20 ft.", (13, 6, 16, 3, 6, 5), [
        "Slam. Melee Weapon Attack: +3 to hit, reach 5 ft. Hit: 4 (1d6 + 1) bludgeoning damage.",
    ], traits=["Undead Fortitude. If damage reduces it to 0 HP, it makes a Constitution save (DC 5 + damage taken) unless the damage is radiant or from a critical hit. On a success it drops to 1 HP instead."],
       immunities="poison", condition_immunities="poisoned",
       senses="darkvision 60 ft., passive Perception 8", languages="understands the languages it knew in life but can't speak"),
    _m("Ghoul", "Medium undead, chaotic evil", "1", 22, 12, "30 ft.", (13, 15, 10, 7, 10, 6), [
        "Bite. Melee Weapon Attack: +2 to hit, reach 5 ft. Hit: 9 (2d6 + 2) piercing damage.",
        "Claws. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 7 (2d4 + 2) slashing damage. A non-elf, non-undead target must succeed on a DC 10 Constitution save or be paralyzed for 1 minute (repeats the save at the end of each turn).",
    ], immunities="poison", condition_immunities="charmed, exhaustion, poisoned",
       senses="darkvision 60 ft., passive Perception 10", languages="Common"),
    _m("Wight", "Medium undead, neutral evil", "3", 45, 14, "30 ft.", (15, 14, 16, 10, 13, 15), [
        "Multiattack. The wight makes two longsword attacks or two longbow attacks. It can use Life Drain in place of one longsword attack.",
        "Life Drain. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 (1d6 + 2) necrotic damage. The target must succeed on a DC 13 Constitution save or its hit point maximum is reduced by the damage taken.",
        "Longsword. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 6 (1d8 + 2) slashing damage, or 7 (1d10 + 2) if used with two hands.",
        "Longbow. Ranged Weapon Attack: +4 to hit, range 150/600 ft. Hit: 6 (1d8 + 2) piercing damage.",
    ], traits=["Sunlight Sensitivity. Disadvantage on attack rolls and sight-based Perception checks in sunlight."],
       resistances="necrotic; bludgeoning, piercing, and slashing from nonmagical attacks that aren't silvered",
       immunities="poison", condition_immunities="exhaustion, poisoned",
       senses="darkvision 60 ft., passive Perception 13", languages="the languages it knew in life"),
    # --- beasts -------------------------------------------------------------------
    _m("Wolf", "Medium beast, unaligned", "1/4", 11, 13, "40 ft.", (12, 15, 12, 3, 12, 6), [
        "Bite. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 7 (2d4 + 2) piercing damage. If the target is a creature, it must succeed on a DC 11 Strength save or be knocked prone.",
    ], traits=["Keen Hearing and Smell. Advantage on Perception checks that rely on hearing or smell.",
               "Pack Tactics. Advantage on attack rolls against a creature if an ally is within 5 ft. of it and isn't incapacitated."],
       senses="passive Perception 13"),
    _m("Dire Wolf", "Large beast, unaligned", "1", 37, 14, "50 ft.", (17, 15, 15, 3, 12, 7), [
        "Bite. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 10 (2d6 + 3) piercing damage. If the target is a creature, it must succeed on a DC 13 Strength save or be knocked prone.",
    ], traits=["Keen Hearing and Smell. Advantage on Perception checks that rely on hearing or smell.",
               "Pack Tactics. Advantage on attack rolls against a creature if an ally is within 5 ft. of it and isn't incapacitated."],
       senses="passive Perception 13"),
    _m("Giant Rat", "Small beast, unaligned", "1/8", 7, 12, "30 ft.", (7, 15, 11, 2, 10, 4), [
        "Bite. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 4 (1d4 + 2) piercing damage.",
    ], traits=["Keen Smell. Advantage on Perception checks that rely on smell.",
               "Pack Tactics. Advantage on attack rolls against a creature if an ally is within 5 ft. of it and isn't incapacitated."],
       senses="darkvision 60 ft., passive Perception 10"),
    _m("Swarm of Rats", "Medium swarm of Tiny beasts, unaligned", "1/4", 24, 10, "30 ft.", (9, 11, 9, 2, 10, 3), [
        "Bites. Melee Weapon Attack: +2 to hit, reach 0 ft., one target in the swarm's space. Hit: 7 (2d6) piercing damage, or 3 (1d6) if the swarm has half its hit points or fewer.",
    ], traits=["Swarm. Can occupy another creature's space and move through openings big enough for a Tiny rat. Can't regain hit points or gain temporary hit points."],
       resistances="bludgeoning, piercing, slashing",
       condition_immunities="charmed, frightened, grappled, paralyzed, petrified, prone, restrained, stunned",
       senses="darkvision 30 ft., passive Perception 10"),
    _m("Giant Spider", "Large beast, unaligned", "1", 26, 14, "30 ft., climb 30 ft.", (14, 16, 12, 2, 11, 4), [
        "Bite. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 7 (1d8 + 3) piercing damage, and the target must make a DC 11 Constitution save, taking 9 (2d8) poison damage on a failure, or half as much on a success.",
        "Web (Recharge 5–6). Ranged Weapon Attack: +5 to hit, range 30/60 ft. Hit: The target is restrained by webbing (DC 12 Strength check to escape; the web has AC 10 and 5 HP).",
    ], traits=["Spider Climb. Can climb difficult surfaces, including upside down on ceilings, without a check.",
               "Web Sense / Web Walker. Knows the location of anything touching its web and ignores webbing movement restrictions."],
       senses="blindsight 10 ft., darkvision 60 ft., passive Perception 10"),
    _m("Brown Bear", "Large beast, unaligned", "1", 34, 11, "40 ft., climb 30 ft.", (19, 10, 16, 2, 13, 7), [
        "Multiattack. The bear makes two attacks: one with its bite and one with its claws.",
        "Bite. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 8 (1d8 + 4) piercing damage.",
        "Claws. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 11 (2d6 + 4) slashing damage.",
    ], traits=["Keen Smell. Advantage on Perception checks that rely on smell."], senses="passive Perception 13"),
    # --- monsters -----------------------------------------------------------------
    _m("Owlbear", "Large monstrosity, unaligned", "3", 59, 13, "40 ft.", (20, 12, 17, 3, 12, 7), [
        "Multiattack. The owlbear makes two attacks: one with its beak and one with its claws.",
        "Beak. Melee Weapon Attack: +7 to hit, reach 5 ft. Hit: 10 (1d10 + 5) piercing damage.",
        "Claws. Melee Weapon Attack: +7 to hit, reach 5 ft. Hit: 14 (2d8 + 5) slashing damage.",
    ], traits=["Keen Sight and Smell. Advantage on Perception checks that rely on sight or smell."],
       senses="darkvision 60 ft., passive Perception 13"),
    _m("Mimic", "Medium monstrosity (shapechanger), neutral", "2", 58, 12, "15 ft.", (17, 12, 15, 5, 13, 8), [
        "Pseudopod. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 7 (1d8 + 3) bludgeoning damage. If the mimic is in object form, the target is stuck to it (escape DC 13).",
        "Bite. Melee Weapon Attack: +5 to hit, reach 5 ft. Hit: 7 (1d8 + 3) piercing damage plus 4 (1d8) acid damage.",
    ], traits=["Shapechanger. Can turn into an object or back to its true form as an action.",
               "Adhesive (object form only). Sticks to anything that touches it; grappled (escape DC 13).",
               "False Appearance (object form only). Indistinguishable from an ordinary object while motionless.",
               "Grappler. Advantage on attack rolls against any creature grappled by it."],
       immunities="acid", condition_immunities="prone", senses="darkvision 60 ft., passive Perception 11"),
    _m("Gelatinous Cube", "Large ooze, unaligned", "2", 84, 6, "15 ft.", (14, 3, 20, 1, 6, 1), [
        "Pseudopod. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 10 (3d6) acid damage.",
        "Engulf. Moves into Large or smaller creatures' spaces. Each must make a DC 12 Dexterity save or be engulfed: 10 (3d6) acid damage, restrained, and 21 (6d6) acid damage at the start of each of the cube's turns.",
    ], traits=["Ooze Cube. Fills its whole space; other creatures can enter it but are subjected to Engulf.",
               "Transparent. A DC 15 Perception check spots it if it hasn't moved or attacked."],
       condition_immunities="blinded, charmed, deafened, exhaustion, frightened, prone",
       senses="blindsight 60 ft. (blind beyond this radius), passive Perception 8"),
    # --- giants -------------------------------------------------------------------
    _m("Ogre", "Large giant, chaotic evil", "2", 59, 11, "40 ft.", (19, 8, 16, 5, 7, 7), [
        "Greatclub. Melee Weapon Attack: +6 to hit, reach 5 ft. Hit: 13 (2d8 + 4) bludgeoning damage.",
        "Javelin. Melee or Ranged Weapon Attack: +6 to hit, reach 5 ft. or range 30/120 ft. Hit: 11 (2d6 + 4) piercing damage.",
    ], senses="darkvision 60 ft., passive Perception 8", languages="Common, Giant"),
    _m("Troll", "Large giant, chaotic evil", "5", 84, 15, "30 ft.", (18, 13, 20, 7, 9, 7), [
        "Multiattack. The troll makes three attacks: one with its bite and two with its claws.",
        "Bite. Melee Weapon Attack: +7 to hit, reach 5 ft. Hit: 7 (1d6 + 4) piercing damage.",
        "Claw. Melee Weapon Attack: +7 to hit, reach 5 ft. Hit: 11 (2d6 + 4) slashing damage.",
    ], traits=["Keen Smell. Advantage on Perception checks that rely on smell.",
               "Regeneration. Regains 10 hit points at the start of its turn. If it takes acid or fire damage, this doesn't work on its next turn. It dies only if it starts its turn with 0 HP and doesn't regenerate."],
       senses="darkvision 60 ft., passive Perception 12", languages="Giant"),
    # --- dragons ------------------------------------------------------------------
    _m("White Dragon Wyrmling", "Medium dragon, chaotic evil", "2", 32, 16, "30 ft., burrow 15 ft., fly 60 ft., swim 30 ft.", (14, 10, 14, 5, 10, 11), [
        "Bite. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 7 (1d10 + 2) piercing damage plus 2 (1d4) cold damage.",
        "Cold Breath (Recharge 5–6). 15-ft. cone, DC 12 Constitution save: 22 (5d8) cold damage on a failure, half on a success.",
    ], immunities="cold", senses="blindsight 10 ft., darkvision 60 ft., passive Perception 14", languages="Draconic"),
    _m("Young Red Dragon", "Large dragon, chaotic evil", "10", 178, 18, "40 ft., climb 40 ft., fly 80 ft.", (23, 10, 21, 14, 11, 19), [
        "Multiattack. The dragon makes three attacks: one with its bite and two with its claws.",
        "Bite. Melee Weapon Attack: +10 to hit, reach 10 ft. Hit: 17 (2d10 + 6) piercing damage plus 3 (1d6) fire damage.",
        "Claw. Melee Weapon Attack: +10 to hit, reach 5 ft. Hit: 13 (2d6 + 6) slashing damage.",
        "Fire Breath (Recharge 5–6). 30-ft. cone, DC 17 Dexterity save: 56 (16d6) fire damage on a failure, half on a success.",
    ], immunities="fire", senses="blindsight 30 ft., darkvision 120 ft., passive Perception 18", languages="Common, Draconic"),
]

BY_NAME = {m["name"]: m for m in MONSTERS}


def cr_value(cr):
    """'1/4' -> 0.25, for sorting and filtering."""
    if "/" in cr:
        a, b = cr.split("/")
        return int(a) / int(b)
    return float(cr)
