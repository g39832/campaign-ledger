"""The join QR code: read back by a small independent reader (format bits and their checksum,
unmasking, the zigzag, de-interleaving, Reed-Solomon syndromes worked out separately, byte mode)
for links of every length the app uses, and the Players page's QR endpoint (DM only)."""
import pytest

from app import qr

LINKS = ["http://192.168.1.10:5050/join?code=E7GLEL",
         "https://mighty-names-tomatoes-contributors.trycloudflare.com/join?code=E7GLEL",
         "https://bibliography-processor-worship-eliminate.trycloudflare.com/join?code=ABC123",
         "a", "x" * 150, "https://" + "y" * 190]

MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
         lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
         lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def gf_tables():
    exp, log = [0] * 512, [0] * 256
    v = 1
    for i in range(255):
        exp[i] = v
        log[v] = i
        v <<= 1
        if v & 0x100:
            v ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


EXP, LOG = gf_tables()


def syndromes_zero(block, necc):
    """Every syndrome of a Reed-Solomon codeword is 0 (evaluating it at a^0 .. a^(necc-1))."""
    for i in range(necc):
        s = 0
        for c in block:
            s = (EXP[(LOG[s] + i) % 255] if s else 0) ^ c
        if s:
            return False
    return True


def function_modules(size, version):
    """Where the fixed patterns are (finders and separators, timing, alignment, format, version)."""
    f = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            if (x < 9 and y < 9) or (x >= size - 8 and y < 9) or (x < 9 and y >= size - 8) or x == 6 or y == 6:
                f[y][x] = True
    if version >= 2:
        n = version // 7 + 2
        step = (version * 8 + n * 3 + 5) // (n * 4 - 4) * 2
        pos = [6] + sorted(size - 7 - i * step for i in range(n - 1))
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        f[b + dy][a + dx] = True
    if version >= 7:
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            f[b][a] = f[a][b] = True
    return f


def read(q):
    m, size = q.modules, q.size
    version = (size - 17) // 4
    # format bits (the copy around the top-left finder)
    spots = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    bits = sum((1 << i) for i, (x, y) in enumerate(spots) if m[y][x]) ^ 0x5412
    data, rem = bits >> 10, bits >> 10
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    assert (data << 10 | rem) == bits, "format bits checksum"
    ecl, mask = data >> 3, data & 7
    assert ecl == 0, "error correction level M"
    func = function_modules(size, version)
    # the data squares, in the zigzag order, unmasked
    out, right = [], size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not func[y][x]:
                    out.append(m[y][x] ^ MASKS[mask](x, y))
        right -= 2
    total = len(out) // 8
    cw = [int("".join("1" if b else "0" for b in out[i * 8:i * 8 + 8]), 2) for i in range(total)]
    # de-interleave the blocks, check each with its syndromes
    nb, necc = qr.NUM_BLOCKS[version], qr.ECC_PER_BLOCK[version]
    nshort, short = nb - total % nb, total // nb
    lens = [short - necc + (0 if i < nshort else 1) for i in range(nb)]
    blocks, k = [[] for _ in range(nb)], 0
    for i in range(max(lens)):
        for j in range(nb):
            if i < lens[j]:
                blocks[j].append(cw[k]); k += 1
    for i in range(necc):
        for j in range(nb):
            blocks[j].append(cw[k]); k += 1
    for j in range(nb):
        assert syndromes_zero(blocks[j], necc), f"block {j} fails its error correction check"
    payload = [b for j in range(nb) for b in blocks[j][:lens[j]]]
    bits = "".join(f"{b:08b}" for b in payload)
    assert bits[:4] == "0100", "byte mode"
    nlen = 8 if version <= 9 else 16
    n = int(bits[4:4 + nlen], 2)
    return bytes(int(bits[4 + nlen + 8 * i: 12 + nlen + 8 * i], 2) for i in range(n)).decode("utf-8")


@pytest.mark.parametrize("text", LINKS)
def test_qr_reads_back(text):
    q = qr.QR(text)
    assert read(q) == text
    assert q.size == q.version * 4 + 17 and 1 <= q.version <= 10


def test_too_long_is_refused():
    with pytest.raises(ValueError):
        qr.QR("z" * 300)


def test_the_players_page_qr_is_for_the_dm(app, api):
    r = api.c.get("/api/join-qr?url=" + "http%3A%2F%2F192.168.1.10%3A5050%2Fjoin%3Fcode%3DE7GLEL")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data.startswith(bytes([0x89]) + b"PNG")
    assert api.c.get("/api/join-qr?url=javascript:alert(1)").status_code == 400
    from tests.test_dice_map_players import remote
    other = remote(app, "192.168.1.40")  # another device on the Wi-Fi, not the DM
    assert other.c.get("/api/join-qr?url=http%3A%2F%2Fx").status_code in (401, 403)


def test_the_png_itself_reads_back(app, api):
    """Sample the picture the page shows, square by square, and read it."""
    import io
    from urllib.parse import quote
    from PIL import Image
    url = "https://mighty-names-tomatoes-contributors.trycloudflare.com/join?code=E7GLEL"
    r = api.c.get("/api/join-qr?scale=6&url=" + quote(url, safe=""))
    img = Image.open(io.BytesIO(r.data)).convert("L")
    q = qr.QR(url)
    n, border, scale = q.size, 4, 6
    assert img.size == ((n + 2 * border) * scale,) * 2
    px = img.load()
    q.modules = [[px[(x + border) * scale + scale // 2, (y + border) * scale + scale // 2] < 128 for x in range(n)] for y in range(n)]
    assert read(q) == url
    assert all(px[i, 0] > 128 for i in range(img.size[0]))  # a white quiet zone around it
