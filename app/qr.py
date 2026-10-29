"""QR codes for the join link (byte mode, error correction M, versions 1-10: links up to 213 bytes).

A small port of Project Nayuki's QR Code generator (MIT License, Copyright (c) Project Nayuki,
https://www.nayuki.io/page/qr-code-generator-library), cut down to what the app needs, so it
works offline with no new dependency. png() draws it with Pillow."""
import io

# per version 1-10 (index 0 unused), error correction level M
ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
NUM_BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
ECL_M_BITS = 0  # format bits for level M
MAX_VERSION = 10


def _raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver]


def _rs_multiply(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_multiply(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_multiply(coef, factor)
    return result


def _alignment_positions(ver):
    if ver == 1:
        return []
    num = ver // 7 + 2
    step = (ver * 8 + num * 3 + 5) // (num * 4 - 4) * 2
    result = [ver * 4 + 10 - i * step for i in range(num - 1)]
    return [6] + list(reversed(result))


class QR:
    def __init__(self, text):
        data = text.encode("utf-8")
        for ver in range(1, MAX_VERSION + 1):
            cap_bits = _data_codewords(ver) * 8
            need = 4 + (8 if ver <= 9 else 16) + len(data) * 8
            if need <= cap_bits:
                break
        else:
            raise ValueError("Too long for a QR code here")
        self.version, self.size = ver, ver * 4 + 17
        bits = []

        def add(val, n):
            bits.extend((val >> i) & 1 for i in reversed(range(n)))
        add(0b0100, 4)
        add(len(data), 8 if ver <= 9 else 16)
        for b in data:
            add(b, 8)
        add(0, min(4, cap_bits - len(bits)))
        add(0, (-len(bits)) % 8)
        pad = 0xEC
        while len(bits) < cap_bits:
            add(pad, 8)
            pad ^= 0xEC ^ 0x11
        codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
        allcw = self._add_ecc_and_interleave(codewords)
        n = self.size
        self.modules = [[False] * n for _ in range(n)]
        self.is_function = [[False] * n for _ in range(n)]
        self._draw_function_patterns()
        self._draw_codewords(allcw)
        best, best_penalty = 0, None
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format_bits(mask)
            p = self._penalty()
            if best_penalty is None or p < best_penalty:
                best, best_penalty = mask, p
            self._apply_mask(mask)  # undo (XOR)
        self._apply_mask(best)
        self._draw_format_bits(best)
        self.mask = best

    # -- building ------------------------------------------------------------------------
    def _add_ecc_and_interleave(self, data):
        ver = self.version
        nblocks, blockecc = NUM_BLOCKS[ver], ECC_PER_BLOCK[ver]
        raw = _raw_modules(ver) // 8
        nshort = nblocks - raw % nblocks
        shortlen = raw // nblocks
        divisor = _rs_divisor(blockecc)
        blocks, k = [], 0
        for i in range(nblocks):
            dat = data[k:k + shortlen - blockecc + (0 if i < nshort else 1)]
            k += len(dat)
            ecc = _rs_remainder(dat, divisor)
            if i < nshort:
                dat = dat + [0]
            blocks.append(dat + ecc)
        result = []
        for i in range(len(blocks[0])):
            for j, blk in enumerate(blocks):
                if i != shortlen - blockecc or j >= nshort:
                    result.append(blk[i])
        assert len(result) == raw
        return result

    def _set(self, x, y, dark):
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def _draw_function_patterns(self):
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self._set(x, y, d not in (2, 4))
        pos = _alignment_positions(self.version)
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format_bits(0)
        self._draw_version()

    def _draw_format_bits(self, mask):
        data = ECL_M_BITS << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        g = lambda i: (bits >> i) & 1 != 0
        n = self.size
        for i in range(6):
            self._set(8, i, g(i))
        self._set(8, 7, g(6))
        self._set(8, 8, g(7))
        self._set(7, 8, g(8))
        for i in range(9, 15):
            self._set(14 - i, 8, g(i))
        for i in range(8):
            self._set(n - 1 - i, 8, g(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, g(i))
        self._set(8, n - 8, True)

    def _draw_version(self):
        if self.version < 7:
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.version << 12 | rem
        n = self.size
        for i in range(18):
            bit = (bits >> i) & 1 != 0
            a, b = n - 11 + i % 3, i // 3
            self._set(a, b, bit)
            self._set(b, a, bit)

    def _draw_codewords(self, data):
        n, i = self.size, 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.is_function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 != 0
                        i += 1
            right -= 2

    def _apply_mask(self, mask):
        f = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
             lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
             lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0][mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and f(x, y):
                    self.modules[y][x] = not self.modules[y][x]

    def _penalty(self):
        n, m, score = self.size, self.modules, 0
        for line in [m[y] for y in range(n)] + [[m[y][x] for y in range(n)] for x in range(n)]:
            run_color, run = line[0], 1
            for v in line[1:]:
                if v == run_color:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    run_color, run = v, 1
            s = "".join("1" if v else "0" for v in line)
            for pat in ("10111010000", "00001011101"):
                score += 40 * s.count(pat)
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(v for row in m for v in row)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        score += max(0, k) * 10
        return score


def png(text, scale=8, border=4):
    """The QR code for text as PNG bytes (dark on white)."""
    from PIL import Image
    q = QR(text)
    n = q.size + border * 2
    img = Image.new("1", (n, n), 1)
    px = img.load()
    for y in range(q.size):
        for x in range(q.size):
            if q.modules[y][x]:
                px[x + border, y + border] = 0
    img = img.resize((n * scale, n * scale), Image.NEAREST)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
