"""Image normalisation for timetable posters.

The 2026 posters draw the hour column as white digits on a saturated pill.
The OCR engine extracts dark ink, so those digits are invisible.  This module
repaints every small coloured fill white and its light glyphs black, leaving
normal dark-on-light text untouched, and caps the width so that very large
scans (5000 px) behave like the 2400 px ones the engine was tuned on.
"""
import numpy as np
from PIL import Image
from scipy import ndimage


def prep(src, dst, max_width=2400):
    """Write a normalised copy of ``src`` to ``dst`` (JPEG)."""
    im = Image.open(src).convert('RGB')
    if im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)),
                       Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-3)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    fill = (sat > 0.12) & (lum > 0.50) & (lum < 0.97)
    fill = ndimage.binary_opening(fill, np.ones((3, 3)))
    fill = ndimage.binary_closing(fill, np.ones((5, 5)))
    lab, _ = ndimage.label(fill)

    gray = lum * 255
    out = gray.copy()
    height, width = gray.shape
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        comp = lab[sl] == i
        if comp.sum() < 150:
            continue
        h, w = comp.shape
        if w > 0.30 * width:
            continue
        reg = out[sl]
        if w < 0.09 * width and h > 0.25 * height:
            # one tall connected strip (燕房-style hour column): every light
            # pixel next to the coloured strip is a glyph
            near = ndimage.binary_dilation(comp, np.ones((3, 3)), iterations=1)
            text = near & ~comp & (reg > 150)
            reg[comp] = 255
            reg[text] = 0
            continue
        holes = ndimage.binary_fill_holes(comp) & ~comp
        reg[comp] = 255
        reg[holes] = np.where(reg[holes] > 140, 0, reg[holes])

    Image.fromarray(out.astype(np.uint8)).save(dst, quality=95)
