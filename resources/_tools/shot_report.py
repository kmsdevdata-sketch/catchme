#!/usr/bin/env python3
"""Render a catchme Markdown report (or selected sections) to a PNG screenshot.

  shot_report.py REPORT.md OUT.png [--sections "Summary,Results"] [--title-only] [--width 1100]

Needs: python `markdown` + `Pillow`, Google Chrome (headless). Used to build resources/ images.
Sections are matched by `## ` heading prefix (case-insensitive). The title + verdict line are always kept.
"""
import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown
from PIL import Image, ImageChops

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
:root { color-scheme: light; }
body { font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
       margin: 0; padding: 28px 36px; background: #ffffff; color: #1f2328; font-size: 15px; line-height: 1.55; }
h1 { font-size: 22px; border-bottom: 1px solid #d0d7de; padding-bottom: 8px; margin-top: 0; }
h2 { font-size: 18px; border-bottom: 1px solid #d8dee4; padding-bottom: 6px; margin-top: 26px; }
h3 { font-size: 15.5px; margin: 18px 0 6px; }
table { border-collapse: collapse; margin: 10px 0 16px; font-size: 13.5px; }
th, td { border: 1px solid #d0d7de; padding: 5px 10px; vertical-align: top; }
th { background: #f6f8fa; }
tr:nth-child(2n) td { background: #fbfcfd; }
code { font-family: "JetBrains Mono", Menlo, monospace; font-size: 12.5px; background: #eff1f3; padding: 1px 5px; border-radius: 5px; }
blockquote { margin: 8px 0; padding: 2px 14px; color: #59636e; border-left: 4px solid #d0d7de; }
p strong { color: #0b5cad; }
ul { padding-left: 22px; }
.badge { display:inline-block; font: 600 12px -apple-system, sans-serif; color:#fff; background:#1f6feb; border-radius: 12px; padding: 3px 10px; margin-bottom: 10px; }
"""


def select_sections(md, wanted):
    if not wanted:
        return md
    parts = re.split(r"(?m)^(?=## )", md)
    head, rest = parts[0], parts[1:]
    keep = [p for p in rest if any(p[3:].strip().lower().startswith(w.lower()) for w in wanted)]
    return head + "".join(keep)


def autocrop(path, pad=24):
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        im = im.crop((0, 0, im.width, min(im.height, bbox[3] + pad)))
    im.save(path, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("out")
    ap.add_argument("--sections", default="")
    ap.add_argument("--badge", default="", help="small label above the report, e.g. 'Spring Boot + JPA'")
    ap.add_argument("--width", type=int, default=1100)
    a = ap.parse_args()

    md = Path(a.report).read_text()
    md = select_sections(md, [s.strip() for s in a.sections.split(",") if s.strip()])
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    badge = f'<div class="badge">{html.escape(a.badge)}</div>' if a.badge else ""
    page = f"<!doctype html><meta charset='utf-8'><style>{CSS}</style><body>{badge}{body}</body>"
    height = 400 + 30 * md.count("\n")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "report.html"
        f.write_text(page)
        out = Path(a.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
               f"--window-size={a.width},{height}", f"--screenshot={out}", f.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not out.exists():
            sys.exit(f"chrome failed: {r.stderr[-400:]}")
    autocrop(out)
    print(out)


if __name__ == "__main__":
    if not shutil.which(CHROME) and not Path(CHROME).exists():
        sys.exit("Google Chrome not found")
    main()
