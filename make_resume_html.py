#!/usr/bin/env python3
"""Render resume_data.json as responsive HTML for the phone breakpoint.

A page image cannot reflow. At 390px an 8.5x11 render is roughly 6pt type, so
it fits the screen without being readable. This emits the same content as real
text that wraps, scales with the reader's font settings, and can be selected
and searched.

Built from resume_data.json so the web copy cannot drift from the PDF.

    py make_resume_html.py [dark|light|inherit] > website/resume.html
"""
import html
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "resume_data.json")

CSS = """
.rz{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
line-height:1.5;color:__FG__;max-width:640px;margin:0 auto;padding:0 4px}
.rz h1{font-size:1.6rem;font-weight:700;margin:0 0 .35rem;color:#8B1A1A;
letter-spacing:-.01em}
.rz .contact{font-size:.8rem;opacity:.75;margin:0 0 1.4rem;word-break:break-word}
.rz .contact a{color:inherit;text-decoration:none;border-bottom:1px solid
currentColor;opacity:.9}
.rz h2{font-size:.78rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
color:#8B1A1A;margin:1.5rem 0 .5rem;padding-bottom:.25rem;
border-bottom:1px solid rgba(139,26,26,.35)}
.rz .row{display:flex;justify-content:space-between;gap:.75rem;flex-wrap:wrap}
.rz .t{font-weight:600;font-size:.95rem}
.rz .m{font-size:.8rem;opacity:.7;white-space:nowrap}
.rz .sub{font-style:italic;font-size:.87rem;opacity:.85}
.rz .item{margin:0 0 1rem}
.rz ul{margin:.4rem 0 0;padding-left:1.1rem}
.rz li{margin:0 0 .35rem;font-size:.88rem}
.rz .meta{font-size:.82rem;margin:.3rem 0 0}
.rz .meta b{font-weight:600}
.rz .skills{font-size:.85rem;margin:.4rem 0 0}
@media(min-width:700px){.rz h1{font-size:2rem}.rz li,.rz .skills{font-size:.92rem}}
"""


def e(s):
    return html.escape(str(s or ""))


def linkify(k, v):
    if k == "email":
        return f'<a href="mailto:{e(v)}">{e(v)}</a>'
    if k in ("website", "github", "linkedin"):
        return f'<a href="https://{e(v)}">{e(v)}</a>'
    return e(v)


def block(name, location, role, date, bullets):
    out = [f'<div class="item"><div class="row"><span class="t">{e(name)}</span>'
           f'<span class="m">{e(location)}</span></div>']
    if role or date:
        out.append(f'<div class="row"><span class="sub">{e(role)}</span>'
                   f'<span class="m">{e(date)}</span></div>')
    if bullets:
        out.append("<ul>" + "".join(f"<li>{e(b['text'])}</li>" for b in bullets) + "</ul>")
    out.append("</div>")
    return "".join(out)


def main():
    # Framer renders an Embed inside an iframe, where `color: inherit` resolves
    # to the iframe default (black) rather than the page. On a dark site that
    # is invisible text, so the colour is written out explicitly.
    theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
    fg = {"dark": "#e8e8e5", "light": "#1a1a1a", "inherit": "inherit"}[theme]
    global CSS
    CSS = CSS.replace("__FG__", fg)

    d = json.load(open(DATA, encoding="utf-8"))
    c = d["contact"]
    bits = [linkify(k, c[k]) for k in
            ("location", "email", "website", "github", "linkedin", "availability")
            if c.get(k)]

    o = [f"<style>{CSS}</style>", '<div class="rz">',
         f'<h1>{e(d["name"])}</h1>',
         f'<p class="contact">{" &middot; ".join(bits)}</p>']

    o.append("<h2>Education</h2>")
    for ed in d["education"]:
        o.append(f'<div class="item"><div class="row"><span class="t">{e(ed["school"])}</span>'
                 f'<span class="m">{e(ed.get("location"))}</span></div>'
                 f'<div class="row"><span class="sub">{e(ed["degree"])}'
                 + (f'; GPA: {e(ed["gpa"])}' if ed.get("gpa") else "")
                 + f'</span><span class="m">{e(ed.get("date"))}</span></div>')
        for label, key in (("Relevant coursework", "coursework"),
                           ("In progress", "in_progress"), ("Honors", "honors")):
            if ed.get(key):
                o.append(f'<p class="meta"><b>{label}:</b> {e(ed[key])}</p>')
        o.append("</div>")

    o.append("<h2>Experience</h2>")
    for x in d["experience"]:
        o.append(block(x["org"], x.get("location"), x.get("role"), x.get("date"),
                       x.get("bullets")))

    o.append("<h2>Projects</h2>")
    for p in d["projects"]:
        o.append(block(p["name"], p.get("location"), p.get("role"), p.get("date"),
                       p.get("bullets")))

    o.append("<h2>Skills</h2>")
    s = d["skills"]
    parts = [", ".join(s["languages"])]
    if s.get("familiar"):
        parts.append("Familiar: " + ", ".join(s["familiar"]))
    parts += [", ".join(s["tools"]), ", ".join(s["concepts"])]
    o.append(f'<p class="skills"><b>Technical:</b> {e("; ".join(parts))}</p>')
    if d.get("affiliations"):
        o.append('<p class="skills"><b>Affiliations:</b> '
                 + e(", ".join(a["name"] for a in d["affiliations"])) + "</p>")

    o.append("</div>")
    sys.stdout.write("\n".join(o))


if __name__ == "__main__":
    main()
