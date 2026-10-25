/* Ready-made spells for the character sheet's "Add from spell list". Each entry is a
   spell row as the sheet stores it: what it does (damage / heal / effect), its dice
   ("mod" = the caster's spellcasting modifier), how it lands (spell attack or a save),
   and any condition or AC change with its duration in rounds (1 minute = 10).
   Short rules summaries only; read the full spell in your book. */
(function () {
  "use strict";
  const S = (name, effect, dice, hit, condition, rounds, ac, notes) => ({ name, effect, dice: dice || "", hit: hit || "", condition: condition || "", rounds: rounds || null, ac: ac || null, notes: notes || "" });
  window.SPELL_BOOK = {
    attribution: "Spell summaries based on the System Reference Document 5.1 by Wizards of the Coast LLC, licensed under CC BY 4.0.",
    spells: [
      // ---- damage
      S("Acid Splash", "damage", "1d6", "dex", "", null, null, "1 action · 60 ft · one or two creatures next to each other · acid"),
      S("Chill Touch", "damage", "1d8", "attack", "", null, null, "1 action · 120 ft · necrotic · target can't regain HP until your next turn"),
      S("Eldritch Blast", "damage", "1d10", "attack", "", null, null, "1 action · 120 ft · force · more beams at higher levels"),
      S("Fire Bolt", "damage", "1d10", "attack", "", null, null, "1 action · 120 ft · fire"),
      S("Poison Spray", "damage", "1d12", "con", "", null, null, "1 action · 10 ft · poison"),
      S("Produce Flame", "damage", "1d8", "attack", "", null, null, "1 action · 30 ft thrown · fire · also sheds light"),
      S("Ray of Frost", "damage", "1d8", "attack", "", null, null, "1 action · 60 ft · cold · speed −10 ft until your next turn"),
      S("Sacred Flame", "damage", "1d8", "dex", "", null, null, "1 action · 60 ft · radiant · no benefit from cover"),
      S("Shocking Grasp", "damage", "1d8", "attack", "", null, null, "1 action · touch · lightning · advantage vs metal armor · target can't take reactions"),
      S("Vicious Mockery", "damage", "1d4", "wis", "", null, null, "1 action · 60 ft · psychic · target has disadvantage on its next attack"),
      S("Burning Hands", "damage", "3d6", "dex", "", null, null, "1 action · 15 ft cone · fire · half on a save"),
      S("Guiding Bolt", "damage", "4d6", "attack", "", null, null, "1 action · 120 ft · radiant · next attack on the target has advantage"),
      S("Inflict Wounds", "damage", "3d10", "attack", "", null, null, "1 action · touch · necrotic"),
      S("Magic Missile", "damage", "3d4+3", "", "", null, null, "1 action · 120 ft · force · three darts that always hit, split them as you like"),
      S("Thunderwave", "damage", "2d8", "con", "", null, null, "1 action · 15 ft cube · thunder · pushed 10 ft on a fail, half on a save"),
      S("Scorching Ray", "damage", "2d6", "attack", "", null, null, "1 action · 120 ft · fire · three rays, roll each"),
      S("Shatter", "damage", "3d8", "con", "", null, null, "1 action · 60 ft · 10 ft sphere · thunder · half on a save"),
      S("Spiritual Weapon", "damage", "1d8+mod", "attack", "", null, null, "1 bonus action · 60 ft · force · lasts 1 minute, attack again as a bonus action"),
      S("Fireball", "damage", "8d6", "dex", "", null, null, "1 action · 150 ft · 20 ft sphere · fire · half on a save"),
      S("Lightning Bolt", "damage", "8d6", "dex", "", null, null, "1 action · 100 ft line · lightning · half on a save"),
      // ---- healing
      S("Cure Wounds", "heal", "1d8+mod", "", "", null, null, "1 action · touch"),
      S("Healing Word", "heal", "1d4+mod", "", "", null, null, "1 bonus action · 60 ft"),
      S("Mass Healing Word", "heal", "1d4+mod", "", "", null, null, "1 bonus action · 60 ft · up to six creatures"),
      S("Prayer of Healing", "heal", "2d8+mod", "", "", null, null, "10 minutes · 30 ft · up to six creatures · not in combat"),
      S("Mass Cure Wounds", "heal", "3d8+mod", "", "", null, null, "1 action · 60 ft · up to six creatures in a 30 ft sphere"),
      // ---- AC and other help
      S("Shield", "effect", "", "", "Shield", 1, 5, "1 reaction · self · +5 AC until the start of your next turn · no damage from Magic Missile"),
      S("Shield of Faith", "effect", "", "", "Shield of Faith", 100, 2, "1 bonus action · 60 ft · concentration, up to 10 minutes"),
      S("Haste", "effect", "", "", "Hasted", 10, 2, "1 action · 30 ft · concentration · double speed, advantage on Dex saves, one extra action"),
      S("Bless", "effect", "", "", "Blessed", 10, null, "1 action · 30 ft · up to three creatures · concentration · add 1d4 to attacks and saves"),
      S("Guidance", "effect", "", "", "Guidance", 10, null, "1 action · touch · concentration · add 1d4 to one ability check"),
      S("Resistance", "effect", "", "", "Resistance", 10, null, "1 action · touch · concentration · add 1d4 to one saving throw"),
      S("Sanctuary", "effect", "", "wis", "Sanctuary", 10, null, "1 bonus action · 30 ft · attackers must make a Wis save or pick a new target"),
      // ---- conditions on enemies
      S("Bane", "effect", "", "cha", "Baned", 10, null, "1 action · 30 ft · up to three creatures · concentration · subtract 1d4 from attacks and saves"),
      S("Charm Person", "effect", "", "wis", "Charmed", 600, null, "1 action · 30 ft · 1 hour · advantage on the save if you're fighting it"),
      S("Command", "effect", "", "wis", "Prone", 1, null, "1 action · 60 ft · one-word command, e.g. grovel (prone), flee, halt"),
      S("Entangle", "effect", "", "str", "Restrained", 10, null, "1 action · 90 ft · 20 ft square · concentration · difficult terrain"),
      S("Faerie Fire", "effect", "", "dex", "Outlined", 10, null, "1 action · 60 ft · 20 ft cube · concentration · attacks against them have advantage"),
      S("Fear", "effect", "", "wis", "Frightened", 10, null, "1 action · 30 ft cone · concentration · must drop what it holds and run"),
      S("Hideous Laughter", "effect", "", "wis", "Prone", 10, null, "1 action · 30 ft · concentration · falls prone laughing, incapacitated · new save when it takes damage"),
      S("Hold Person", "effect", "", "wis", "Paralyzed", 10, null, "1 action · 60 ft · humanoid · concentration · save again at the end of each of its turns"),
      S("Sleep", "effect", "", "", "Unconscious", 10, null, "1 action · 90 ft · roll 5d8: creatures with that many HP or fewer fall asleep, lowest first"),
    ],
  };
})();
