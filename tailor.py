#!/usr/bin/env python3
"""
Generates a per-posting tailored resume .docx from resume_data.json.

Tailoring here means SELECTION and ORDERING ONLY:
  - projects reordered by keyword overlap with the real job description
  - skills reordered so the ones the posting names appear first
  - a project dropped only when the resume would otherwise spill past one page

It never rewrites a bullet and never adds a claim. Every string it emits comes
verbatim from resume_data.json, which is transcribed from the real resume.
If a posting wants something not in that file, the honest answer is that the
resume does not have it -- the gap belongs in the brief, not invented here.

Usage:
    py tailor.py --brief briefs/RTX-...-01863012.md
    py tailor.py --all-apply          tailor every brief marked APPLY
"""
import argparse
import json
import os
import re
import sys

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.shared import Inches, Pt, RGBColor
except ImportError:
    sys.exit("python-docx is required:  py -m pip install python-docx")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")
# tailored/ is the STAGING area -- it holds only the resume for the posting
# being applied to right now, so the ATS file picker has exactly one choice.
# tailored/Storage/ is the archive where every generated resume actually lives.
STAGE_DIR = os.path.join(BASE_DIR, "tailored")
OUT_DIR = os.path.join(STAGE_DIR, "Storage")
DATA_PATH = os.path.join(BASE_DIR, "resume_data.json")

# Keeps the generated resume to a single page.
MAX_PROJECTS = 4

# One accent colour, used only on the name and section headings. Resumes that
# colour body text read as decorated; one restrained accent reads as designed.
# Deep maroon matches the original resume. Navy 1F3864 is the other safe pick.
ACCENT = RGBColor(0x8B, 0x1A, 0x1A)

# Words that carry no signal for matching.
STOP = set("""a an the and or of to in for with on at by as is are be been will
would can could should must have has had you your we our they their this that
these those from into out up down over under more most other some such only own
same than too very just also role work team teams year years experience
qualifications preferred required responsibilities including include""".split())


def resume_prefix():
    """Filename prefix for generated resumes, taken from resume_data.json so
    the tool isn't hardcoded to one candidate."""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            name = json.load(f).get("name", "Resume")
    except Exception:
        name = "Resume"
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Resume"


def desc_from_brief(path):
    txt = open(path, encoding="utf-8").read()
    m = re.search(r"^## Full description\s*$(.*)", txt, re.S | re.M)
    return (m.group(1) if m else txt).lower()


def quota_blocked_brief(path):
    """True if this posting's employer has no applications left.

    Without this, --all-apply keeps regenerating resumes for companies whose
    application allowance is spent -- 36 files for TikTok/ByteDance alone.
    """
    from datetime import date
    try:
        cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
    except Exception:
        return False
    company = os.path.basename(path).split("-")[0].lower()
    today = date.today().isoformat()
    for rule in cfg.get("quota_exhausted", []):
        if rule.get("until") and rule["until"] < today:
            continue
        if any(m.lower() in company for m in rule.get("match", [])):
            return True
    return False


def verdict_from_brief(path):
    m = re.search(r"^\*\*Verdict:\*\*\s*(\w+)", open(path, encoding="utf-8").read(), re.M)
    return m.group(1) if m else "UNKNOWN"


def company_title(path):
    first = open(path, encoding="utf-8").readline().lstrip("# ").strip()
    parts = [p.strip() for p in first.split("—", 1)]
    return (parts[0], parts[1] if len(parts) > 1 else "")


def relevance(tags, desc):
    """How strongly a tagged item matches the posting text."""
    score = 0
    for t in tags:
        t = t.lower()
        if t in STOP:
            continue
        if t in desc:
            score += 3 if len(t) > 4 else 2
    return score


def order_projects(data, desc):
    scored = []
    for i, p in enumerate(data["projects"]):
        tags = list(p.get("tags", []))
        for b in p.get("bullets", []):
            tags += b.get("tags", [])
        # -i keeps original order as the tiebreak so output is deterministic
        scored.append((relevance(tags, desc), -i, p))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [p for _, _, p in scored], {id(p): s for s, _, p in scored}


def order_skills(data, desc):
    out = {}
    for group, items in data["skills"].items():
        hit = [s for s in items if s.lower().split("/")[0] in desc]
        rest = [s for s in items if s not in hit]
        out[group] = hit + rest
    return out


# ------------------------------------------------------------------ docx build
def _tabbed(doc, left, right, bold_left=True, italic_left=False):
    """One line with left text and a right-aligned date/location."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(7.0), WD_TAB_ALIGNMENT.RIGHT)
    r = p.add_run(left)
    r.bold = bold_left
    r.italic = italic_left
    p.add_run("\t" + right)
    return p


def _heading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = ACCENT
    pr = p._p.get_or_add_pPr()
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "8B1A1A")
    bdr.append(bottom)
    pr.append(bdr)
    return p


def _bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.left_indent = Inches(0.25)
    p.add_run(text)
    return p


def build_docx(data, projects, skills, out_path, max_projects=None):
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Inches(0.5)
        s.left_margin = s.right_margin = Inches(0.6)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    # header
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.paragraph_format.space_after = Pt(0)
    r = h.add_run(data["name"])
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = ACCENT

    c = data["contact"]
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(4)
    # Build from whatever keys exist so adding a contact field doesn't need a
    # code change -- the website was silently absent because it was hardcoded.
    bits = [c[k] for k in ("location", "phone", "email", "website", "github", "linkedin")
            if c.get(k)]
    sub.add_run(" • ".join(bits)).font.size = Pt(9)

    # education
    _heading(doc, "Education")
    for e in data["education"]:
        _tabbed(doc, e["school"], e["location"])
        line = e["degree"] + (f"; GPA: {e['gpa']}" if e.get("gpa") else "")
        p = _tabbed(doc, line, e["date"], bold_left=False, italic_left=True)
        p.runs[0].font.size = Pt(10)
        if e.get("coursework"):
            q = doc.add_paragraph()
            q.paragraph_format.space_after = Pt(0)
            q.add_run("Relevant Coursework: ").bold = True
            q.add_run(e["coursework"]).font.size = Pt(9)
        if e.get("in_progress"):
            q = doc.add_paragraph()
            q.paragraph_format.space_after = Pt(0)
            q.add_run("In Progress: ").bold = True
            q.add_run(e["in_progress"]).font.size = Pt(9)
        if e.get("honors"):
            q = doc.add_paragraph()
            q.paragraph_format.space_after = Pt(0)
            q.add_run("Honors: ").bold = True
            q.add_run(e["honors"]).font.size = Pt(9)

    # experience
    _heading(doc, "Experience")
    for x in data["experience"]:
        _tabbed(doc, x["org"], x["location"])
        p = _tabbed(doc, x["role"], x["date"], bold_left=False, italic_left=True)
        p.runs[0].font.size = Pt(10)
        for b in x["bullets"]:
            _bullet(doc, b["text"])

    # projects
    _heading(doc, "Projects")
    shown = projects[:max_projects] if max_projects else projects
    for pr in shown:
        _tabbed(doc, pr["name"], pr["location"])
        p = _tabbed(doc, pr["role"], pr["date"], bold_left=False, italic_left=True)
        p.runs[0].font.size = Pt(10)
        for b in pr["bullets"]:
            _bullet(doc, b["text"])

    # skills
    _heading(doc, "Skills")
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.add_run("Technical: ").bold = True
    parts = [", ".join(skills["languages"])]
    # "Familiar" is a separate tier on purpose: it keeps breadth on the page
    # without implying the same depth as the primary languages.
    if skills.get("familiar"):
        parts.append("Familiar: " + ", ".join(skills["familiar"]))
    parts += [", ".join(skills["tools"]), ", ".join(skills["concepts"])]
    p.add_run("; ".join(parts)).font.size = Pt(9)

    # Affiliations ride under Skills rather than getting their own heading --
    # a section header costs more vertical space than the content is worth,
    # and the resume has to stay on one page.
    if data.get("affiliations"):
        # Right-align the date the same way Education/Experience/Projects do,
        # so the line reads as part of the document rather than an afterthought.
        for a in data["affiliations"]:
            q = doc.add_paragraph()
            q.paragraph_format.space_after = Pt(0)
            q.paragraph_format.tab_stops.add_tab_stop(
                Inches(7.0), WD_TAB_ALIGNMENT.RIGHT)
            q.add_run("Affiliations: ").bold = True
            q.add_run(a["name"]).font.size = Pt(9)
            # Date is optional and usually omitted: a membership is a current
            # state, not something with a duration, and dating a brand-new one
            # just advertises how new it is.
            if a.get("date"):
                q.add_run("	" + a["date"]).font.size = Pt(9)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path)
    return out_path


def tailor_one(brief_path, data, quiet=False, force=False, max_projects=None):
    stem = os.path.splitext(os.path.basename(brief_path))[0]
    out = os.path.join(OUT_DIR, f"{resume_prefix()}_{stem}.docx")

    # Skip work already done -- the scheduled run calls this every time, and
    # regenerating an unchanged resume would clobber any manual edits.
    if os.path.exists(out) and not force:
        if not quiet:
            print(f"  [exists] {os.path.basename(out)}")
        return out

    desc = desc_from_brief(brief_path)
    company, title = company_title(brief_path)
    projects, scores = order_projects(data, desc)
    skills = order_skills(data, desc)
    try:
        # A second page on an intern resume is a cost, not a bonus: recruiters
        # skim page one. Five projects overflow, so cap the list and let the
        # relevance ordering decide which one is least worth the space.
        #
        # Four is right for most postings, but the cap is content-blind: it
        # counts projects, not lines. A posting whose fourth-ranked project
        # happens to carry two bullets instead of one can still spill onto a
        # second page, so the limit is overridable per posting.
        build_docx(data, projects, skills, out,
                   max_projects=max_projects or MAX_PROJECTS)
    except PermissionError:
        # Word holds an exclusive lock on an open .docx. Skip it and keep
        # going rather than aborting the whole batch partway through.
        print(f"  [locked] {os.path.basename(out)} -- open in Word, skipped")
        return None

    if not quiet:
        print(f"\n{company} — {title}")
        print(f"  verdict : {verdict_from_brief(brief_path)}")
        print("  project order (by match to this description):")
        for p in projects:
            print(f"      {scores[id(p)]:>3}  {p['name']}")
        print(f"  -> {os.path.relpath(out, BASE_DIR)}")
    return out


def stage(pattern):
    """Clear the staging folder, then copy in the one resume being applied to.

    Storage/ always keeps the master copy, so clearing the staging folder only
    ever deletes a duplicate -- nothing generated is lost.
    """
    import shutil
    os.makedirs(OUT_DIR, exist_ok=True)
    all_res = [f for f in os.listdir(OUT_DIR) if f.endswith(".docx")]
    hits = [f for f in all_res if pattern.lower() in f.lower()]

    if not hits:
        print(f"No resume in Storage matches '{pattern}'. Available:")
        for f in sorted(all_res):
            print(f"  {f}")
        return 1
    if len(hits) > 1:
        print(f"'{pattern}' matches {len(hits)} resumes -- be more specific:")
        for f in sorted(hits):
            print(f"  {f}")
        return 1

    cleared = 0
    for f in os.listdir(STAGE_DIR):
        p = os.path.join(STAGE_DIR, f)
        if os.path.isfile(p) and f.endswith(".docx"):
            os.remove(p)
            cleared += 1

    src = os.path.join(OUT_DIR, hits[0])
    dst = os.path.join(STAGE_DIR, hits[0])
    shutil.copy2(src, dst)

    print(f"Staged: {hits[0]}")
    if cleared:
        print(f"Cleared {cleared} previous file(s) from tailored/ (masters kept in Storage/).")
    print(f"\ntailored/ now contains exactly one resume:\n  {dst}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief")
    ap.add_argument("--all-apply", action="store_true",
                    help="build resumes for APPLY and REVIEW briefs")
    ap.add_argument("--stage", metavar="PATTERN",
                    help="clear tailored/ and stage the one Storage resume matching PATTERN "
                         "(e.g. --stage appian)")
    ap.add_argument("--list", action="store_true", help="list resumes in Storage")
    ap.add_argument("--quiet", action="store_true",
                    help="only report what was newly built (for scheduled runs)")
    ap.add_argument("--max-projects", type=int, metavar="N",
                    help=f"projects to keep on the page (default {MAX_PROJECTS}); "
                         "lower it when a build spills onto a second page")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the .docx already exists")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.stage:
        sys.exit(stage(args.stage))

    if args.list:
        res = sorted(f for f in os.listdir(OUT_DIR) if f.endswith(".docx"))
        print(f"{len(res)} resume(s) in tailored/Storage/:\n")
        for f in res:
            print(f"  {f}")
        active = [f for f in os.listdir(STAGE_DIR)
                  if f.endswith(".docx") and os.path.isfile(os.path.join(STAGE_DIR, f))]
        print(f"\nStaged in tailored/: {active[0] if active else '(none)'}")
        return

    data = json.load(open(DATA_PATH, encoding="utf-8"))

    if args.brief:
        targets = [args.brief if os.path.isabs(args.brief)
                   else os.path.join(BASE_DIR, args.brief)]
    elif args.all_apply:
        targets = [os.path.join(BRIEFS_DIR, f)
                   for f in sorted(os.listdir(BRIEFS_DIR))
                   if f.endswith(".md")]
        # REVIEW is included on purpose. A REVIEW verdict means "read the flags
        # first", not "don't apply" -- the strongest RTX posting is REVIEW
        # because of a boilerplate degree line. Only SKIP is genuinely dead.
        targets = [t for t in targets
                   if verdict_from_brief(t) in ("APPLY", "REVIEW")
                   and not quota_blocked_brief(t)]
    else:
        ap.error("pass --brief <path> or --all-apply")

    if not targets:
        print("No matching briefs.")
        return

    built = 0
    for t in targets:
        stem = os.path.splitext(os.path.basename(t))[0]
        existed = os.path.exists(os.path.join(OUT_DIR, f"{resume_prefix()}_{stem}.docx"))
        tailor_one(t, data, quiet=args.quiet, force=args.force,
                   max_projects=args.max_projects)
        if not existed or args.force:
            built += 1

    if args.quiet:
        print(f"tailor: {built} new resume(s), {len(targets) - built} already present.")
    else:
        print(f"\n{built} new, {len(targets) - built} already present. "
              f"Nothing was uploaded or submitted.")


if __name__ == "__main__":
    main()
