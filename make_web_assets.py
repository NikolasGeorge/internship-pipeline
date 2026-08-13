#!/usr/bin/env python3
"""Render the general resume PDF into web assets for nikolasgeorge.com.

One raster asset at 4x, used at every breakpoint. SVG would stay sharper, but
iOS Safari will not inline-render a PDF and SVG brings its own quirks (a
transparent page background among them), so a single high-resolution PNG is
the format that behaves identically everywhere.

The page is almost entirely white with black text and one accent colour, so an
adaptive palette cuts the file roughly in half with no visible loss.

    py make_web_assets.py [scale]
"""
import os
import sys

import fitz
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "website")
PDF = os.path.join(WEB, "Nikolas_George_Resume.pdf")
OUT = os.path.join(WEB, "Nikolas_George_Resume.png")


def main():
    scale = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    if not os.path.exists(PDF):
        sys.exit(f"missing {PDF} -- run export_pdf.ps1 website first")

    doc = fitz.open(PDF)
    if doc.page_count != 1:
        print(f"  warning: resume is {doc.page_count} pages, rendering page 1 only")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))  # opaque, white page
    tmp = OUT + ".tmp.png"
    pix.save(tmp)
    doc.close()

    im = Image.open(tmp).convert("RGB")
    pal = im.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE)
    pal.save(OUT, optimize=True)
    os.remove(tmp)

    kb = os.path.getsize(OUT) / 1024
    print(f"  {os.path.basename(OUT)}  {im.width}x{im.height}px  {kb:.0f} KB  ({scale}x)")
    print(f"  aspect ratio {im.width / im.height:.4f} "
          f"-- at 800px wide set height to {round(800 / (im.width / im.height))}px")


if __name__ == "__main__":
    main()
