"""Generate assets/icon.ico for Squad Seed Monitor.

Draws a simple, recognizable emblem — a rising player-count line crossing a
dashed target line on a dark rounded tile — matching the app's live graph.
Run:  python tools/make_icon.py   (needs Pillow)
Output: assets/icon.ico (multi-size: 16/32/48/64/128/256)
"""
import os

from PIL import Image, ImageDraw

BG = (36, 52, 71)        # #243447 dark navy tile
GREEN = (47, 165, 114)   # #2fa572 accent line
YELLOW = (241, 196, 15)  # #f1c40f target line
DOT = (230, 230, 230)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def render(size):
    s = size * 4  # supersample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)

    pad = int(s * 0.20)
    w = s - 2 * pad
    # dashed target line near the top
    ty = pad + int(w * 0.12)
    x = pad
    dash = int(s * 0.05)
    while x < s - pad:
        d.line([x, ty, min(x + dash, s - pad), ty], fill=YELLOW, width=max(2, int(s * 0.018)))
        x += dash * 2
    # rising player-count line
    pts = [
        (pad, pad + int(w * 0.85)),
        (pad + int(w * 0.30), pad + int(w * 0.62)),
        (pad + int(w * 0.55), pad + int(w * 0.70)),
        (pad + int(w * 0.80), pad + int(w * 0.28)),
        (s - pad, pad + int(w * 0.10)),
    ]
    d.line(pts, fill=GREEN, width=max(3, int(s * 0.05)), joint="curve")
    # end dot at the top-right of the line
    r = int(s * 0.055)
    ex, ey = pts[-1]
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=DOT)

    img = img.resize((size, size), Image.LANCZOS)
    img.putalpha(rounded_mask(size, int(size * 0.22)))
    return img


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(here, "assets")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "icon.ico")
    sizes = [16, 32, 48, 64, 128, 256]
    base = render(256)
    base.save(out, sizes=[(x, x) for x in sizes])
    print("wrote", out)


if __name__ == "__main__":
    main()
