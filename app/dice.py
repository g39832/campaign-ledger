"""Dice expressions: a tiny tokenizer + parser (never eval) and the roller.

Grammar (case-insensitive, spaces ignored):
    expression := term (("+" | "-") term)*
    term       := dice | integer
    dice       := [count] "d" (sides | "%") [keep]
    keep       := ("kh" | "kl" | "dh" | "dl") [n]     keep/drop highest/lowest

Examples: d20, 1d20+5, 2d6+3, 4d8-1, 2d20kh1, 2d20kl1, 4d6dl1, d%, 3d6+1d4+2
"""
import re
import secrets

ALLOWED_SIDES = (2, 3, 4, 6, 8, 10, 12, 20, 100)
MAX_LENGTH = 80
MAX_TERMS = 12
MAX_DICE_PER_TERM = 50
MAX_DICE_TOTAL = 100
MAX_CONSTANT = 1000

_rng = secrets.SystemRandom()

TOKEN = re.compile(r"\s*(?:(?P<dice>(?P<count>\d*)d(?P<sides>\d+|%)(?:(?P<keep>kh|kl|dh|dl)(?P<keepn>\d*))?)|(?P<num>\d+)|(?P<op>[+-]))", re.I)


class DiceError(ValueError):
    pass


def parse(expr):
    """Return a list of terms: {"type": "dice", "sign", "count", "sides", "keep"} or
    {"type": "mod", "value"}. Raises DiceError with a readable message."""
    if not isinstance(expr, str):
        raise DiceError("Type a dice expression, like 1d20+5")
    text = expr.strip().lower().replace(" ", "")
    if not text:
        raise DiceError("Type a dice expression, like 1d20+5")
    if len(text) > MAX_LENGTH:
        raise DiceError(f"That expression is too long (max {MAX_LENGTH} characters)")
    pos, terms, sign, expect_term = 0, [], 1, True
    total_dice = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise DiceError(f"Can't read “{text[pos:pos + 8]}” — use forms like 2d6+3 or 2d20kh1")
        pos = m.end()
        if m.group("op"):
            if expect_term:
                if not terms and m.group("op") == "-":
                    sign = -1  # leading minus, e.g. "-1+d4"
                    continue
                raise DiceError("Two operators in a row")
            sign = 1 if m.group("op") == "+" else -1
            expect_term = True
            continue
        if not expect_term:
            raise DiceError("Put + or - between terms")
        if m.group("dice"):
            count = int(m.group("count") or 1)
            sides = 100 if m.group("sides") == "%" else int(m.group("sides"))
            if count < 1:
                raise DiceError("Roll at least one die")
            if count > MAX_DICE_PER_TERM:
                raise DiceError(f"At most {MAX_DICE_PER_TERM} dice per group")
            if sides not in ALLOWED_SIDES:
                raise DiceError(f"d{sides} isn't a supported die (use d4, d6, d8, d10, d12, d20 or d100)")
            keep = None
            if m.group("keep"):
                kind = m.group("keep")
                n = int(m.group("keepn") or 1)
                if n < 1 or n > count or (kind in ("dh", "dl") and n >= count):
                    raise DiceError(f"Can't {'keep' if kind[0] == 'k' else 'drop'} {n} of {count} dice")
                keep = {"kind": kind, "n": n}
            total_dice += count
            if total_dice > MAX_DICE_TOTAL:
                raise DiceError(f"At most {MAX_DICE_TOTAL} dice per roll")
            terms.append({"type": "dice", "sign": sign, "count": count, "sides": sides, "keep": keep})
        else:
            value = int(m.group("num"))
            if value > MAX_CONSTANT:
                raise DiceError(f"Modifiers can be at most {MAX_CONSTANT}")
            terms.append({"type": "mod", "value": sign * value})
        if len(terms) > MAX_TERMS:
            raise DiceError(f"At most {MAX_TERMS} terms")
        sign, expect_term = 1, False
    if expect_term:
        raise DiceError("The expression ends with an operator")
    if not any(t["type"] == "dice" for t in terms):
        raise DiceError("Include at least one die, like d20")
    return terms


def normalize(terms):
    out = []
    for i, t in enumerate(terms):
        if t["type"] == "dice":
            s = f"{t['count']}d{t['sides']}" + (f"{t['keep']['kind']}{t['keep']['n']}" if t["keep"] else "")
            sign = t["sign"]
        else:
            s = str(abs(t["value"]))
            sign = 1 if t["value"] >= 0 else -1
        out.append(("-" if sign < 0 else ("+" if i else "")) + s)
    return "".join(out)


def apply_mode(terms, mode):
    """Advantage/disadvantage turns the first single d20 into 2d20 keep
    highest/lowest. Returns True if it applied."""
    if mode not in ("advantage", "disadvantage"):
        return False
    for t in terms:
        if t["type"] == "dice" and t["sides"] == 20 and t["count"] == 1 and not t["keep"]:
            t["count"] = 2
            t["keep"] = {"kind": "kh" if mode == "advantage" else "kl", "n": 1}
            return True
    return False


def double_dice(terms):
    """Critical hit damage: roll twice as many damage dice."""
    for t in terms:
        if t["type"] == "dice":
            t["count"] = min(MAX_DICE_PER_TERM, t["count"] * 2)
    return terms


def roll_terms(terms, rng=None):
    rng = rng or _rng
    out_terms, total, modifier = [], 0, 0
    for t in terms:
        if t["type"] == "mod":
            modifier += t["value"]
            total += t["value"]
            out_terms.append(dict(t))
            continue
        values = [rng.randint(1, t["sides"]) for _ in range(t["count"])]
        kept = [True] * len(values)
        k = t["keep"]
        if k:
            order = sorted(range(len(values)), key=lambda i: (values[i], i))
            if k["kind"] == "kh":
                keep_idx = set(order[-k["n"]:])
            elif k["kind"] == "kl":
                keep_idx = set(order[:k["n"]])
            elif k["kind"] == "dh":
                keep_idx = set(order[:len(values) - k["n"]])
            else:  # dl
                keep_idx = set(order[k["n"]:])
            kept = [i in keep_idx for i in range(len(values))]
        subtotal = sum(v for v, kp in zip(values, kept) if kp)
        total += t["sign"] * subtotal
        out_terms.append(dict(t, rolls=[{"value": v, "kept": kp} for v, kp in zip(values, kept)], subtotal=subtotal))
    natural = None
    d20s = [t for t in out_terms if t["type"] == "dice" and t["sides"] == 20]
    if len(d20s) == 1:
        kept_vals = [r["value"] for r in d20s[0]["rolls"] if r["kept"]]
        if len(kept_vals) == 1:
            natural = kept_vals[0]
    return {"terms": out_terms, "modifier": modifier, "total": total, "natural": natural}


def roll(expr, mode="normal", crit=False, rng=None):
    terms = parse(expr)
    if crit:
        double_dice(terms)
    applied = apply_mode(terms, mode)
    result = roll_terms(terms, rng)
    result["expression"] = normalize(terms)
    result["mode"] = mode if applied else "normal"
    return result


DAMAGE_EXPR = re.compile(r"(\d*d(?:\d+|%)(?:\s*[+-]\s*(?:\d*d(?:\d+|%)|\d+))*)", re.I)
BONUS = re.compile(r"^\s*([+-]?\s*\d+)")


def damage_expression(text):
    """Pull '1d8+3' out of '1d8+3 slashing' or 'Hit: 5 (1d6 + 2) piercing'."""
    m = DAMAGE_EXPR.search(text or "")
    return m.group(1).replace(" ", "") if m else None


D20_PREFIX = re.compile(r"^\s*1?\s*d\s*20\b", re.I)


def attack_bonus(text):
    """'+5' -> 5. People also write the whole roll: '1d20' is +0 and '1d20+2' is +2."""
    text = text or ""
    if D20_PREFIX.match(text):
        rest = D20_PREFIX.sub("", text).strip()
        m = BONUS.match(rest)
        return int(m.group(1).replace(" ", "")) if m else 0
    m = BONUS.match(text)
    return int(m.group(1).replace(" ", "")) if m else None
