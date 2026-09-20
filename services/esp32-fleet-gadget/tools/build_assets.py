#!/usr/bin/env python3
"""Build the sprite blob for the ESP32 firmware from the five approved fighter images.
Layout of sprites.bin (RGB565, BIG-endian words, transparent key 0xF81F): idle x5 (200x240), knocked-out x5 (200x240), small x5 (48x64)."""
import struct, sys
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
NAMES = ["owl", "ox", "fox", "meerkat", "hummingbird"]
CW, CH, SW, SH = 200, 240, 72, 96
KEY = 0xF81F
def cutout(path, thresh=52):
    import numpy as np
    from scipy import ndimage, spatial
    orig = Image.open(path).convert("RGB"); w, h = orig.size
    flood = orig.copy()
    for pt in [(0,0),(w-1,0),(0,h-1),(w-1,h-1),(w//2,0),(w//2,h-1),(0,h//2),(w-1,h//2),(w//4,0),(3*w//4,0),(w//4,h-1),(3*w//4,h-1)]:
        if flood.getpixel(pt) != (255,0,255): ImageDraw.floodfill(flood, pt, (255,0,255), thresh=thresh)
    arr = np.array(orig).astype(np.int16)
    removed = (np.array(flood) == np.array([255, 0, 255])).all(axis=2)
    # enclosed background pockets (between legs, inside a tail): colours close to the removed background, in big blobs
    cols = arr[removed]; sub = cols[::max(1, len(cols) // 4000)]
    d, _ = spatial.cKDTree(sub).query(arr.reshape(-1, 3), k=1); d = d.reshape(h, w)
    cand = (d < 26) & ~removed
    lab, n = ndimage.label(cand)
    if n:
        sizes = ndimage.sum(cand, lab, range(1, n + 1))
        for i, sz in enumerate(sizes, 1):
            if sz >= 250: removed |= (lab == i)
    fg = ndimage.median_filter((~removed).astype(np.uint8) * 255, size=5) > 0
    lab, n = ndimage.label(fg)                                     # keep only substantial foreground pieces
    if n:
        sizes = ndimage.sum(fg, lab, range(1, n + 1)); keep = np.zeros_like(fg)
        for i, sz in enumerate(sizes, 1):
            if sz >= 500: keep |= (lab == i)
        fg = keep
    rgba = orig.convert("RGBA"); rgba.putalpha(Image.fromarray(fg.astype(np.uint8) * 255))
    return rgba.crop(rgba.getbbox())
def fit(img, bw, bh, bottom=True):
    s = min(bw / img.size[0], bh / img.size[1])
    img = img.resize((max(1, round(img.size[0] * s)), max(1, round(img.size[1] * s))), Image.LANCZOS)
    a = img.split()[3].point(lambda v: 255 if v > 140 else 0).filter(ImageFilter.MinFilter(3)); img.putalpha(a)
    can = Image.new("RGBA", (bw, bh), (0,0,0,0))
    can.paste(img, ((bw - img.size[0]) // 2, bh - img.size[1] - 1 if bottom else (bh - img.size[1]) // 2), img)
    return can
def rgb565(can):
    out = bytearray(); px = can.load()
    for y in range(can.size[1]):
        for x in range(can.size[0]):
            r, g, b, a = px[x, y]
            v = KEY if a < 128 else (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
            if a >= 128 and v == KEY: v = 0xF81E
            out += struct.pack(">H", v)
    return bytes(out)
def ko_version(c):
    r = c.rotate(90, expand=True, resample=Image.BICUBIC)
    rgb = r.convert("RGB"); a = r.split()[3]
    rgb = ImageEnhance.Color(rgb).enhance(0.45); rgb = ImageEnhance.Brightness(rgb).enhance(0.8)
    r = rgb.convert("RGBA"); r.putalpha(a)
    return r
blob_idle, blob_ko, blob_small = b"", b"", b""
sheet = Image.new("RGB", (CW * 5, CH + 130), (25, 25, 40))
for i, n in enumerate(NAMES):
    c = cutout(f"art/raw/f_{n}.webp")
    idle = fit(c, CW, CH); ko = fit(ko_version(c), CW - 4, int(CH * 0.62)); koc = Image.new("RGBA", (CW, CH), (0,0,0,0)); koc.paste(ko, (2, CH - ko.size[1] - 1), ko)
    small = fit(c, SW, SH)
    blob_idle += rgb565(idle); blob_ko += rgb565(koc); blob_small += rgb565(small)
    sheet.paste(idle, (i * CW, 0), idle)
    sheet.paste(koc.resize((CW // 2, CH // 2)), (i * CW, CH), koc.resize((CW // 2, CH // 2)))
    sheet.paste(small, (i * CW + 110, CH + 20), small)
    print(n, "cutout", c.size)
open("sprites.bin", "wb").write(blob_idle + blob_ko + blob_small)
sheet.save("art/sprites/assets_preview.png")
print("sprites.bin bytes:", len(blob_idle + blob_ko + blob_small), "(idle", len(blob_idle), "ko", len(blob_ko), "small", len(blob_small), ")")
