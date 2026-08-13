#!/usr/bin/env python3
"""Pre-submission checks on the staged resumes.

Answers the only question that matters before hitting submit: is every claim
on this page true, current, and consistent with the source data? Reads the
.docx files themselves rather than resume_data.json, because the file that
gets uploaded is the one that has to be right.

Usage:
    py check_resumes.py                  check everything in tailored/
    py check_resumes.py <pattern>        check matching staged resumes
"""
import glob
import json
import os
import re
import sys

from docx import Document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STAGE_DIR = os.path.join(BASE_DIR, "tailored")
DATA_PATH = os.path.join(BASE_DIR, "resume_data.json")
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")

# Section labels build_docx emits itself; everything else must come from data.
TEMPLATE_WORDS = {
    "education", "experience", "projects", "skills", "relevant", "coursework",
    "progress", "honors", "technical", "familiar", "affiliations",
}

# Phrases that would misstate the clearance. It lapsed in 2022 and saying
# otherwise on a federal-adjacent application is the one unrecoverable error.
CLEARANCE_RED_FLAGS = [
    r"active\s+(?:secret|ts/sci|top secret)?\s*clearance",
    r"currently\s+cleared",
    r"\bcleared\s+(?:to|at)\b",
    r"clearance:\s*active",
]


def text_of(path):
    return "\n".join(p.text for p in Document(path).paragraphs)


def check(path, data):
    name = os.path.basename(path)
    txt = text_of(path)
    low = txt.lower()
    source = json.dumps(data).lower()
    fails, warns = [], []

    # 1. Nothing invented -- every substantive word traces to the source data.
    for word in re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", txt):
        w = word.lower().strip("'-")
        if w and w not in source and w not in TEMPLATE_WORDS:
            fails.append(f"word not in resume_data.json: {word!r}")

    # 2. Clearance is never described as active.
    for pat in CLEARANCE_RED_FLAGS:
        if re.search(pat, low):
            fails.append(f"clearance may read as active: matched /{pat}/")
    if "clearance" in low and "secret security clearance" not in low:
        warns.append("mentions clearance in unexpected phrasing -- read it")

    # 3. Contact details match the source exactly.
    c = data["contact"]
    for key in ("email", "phone", "website", "github"):
        if c.get(key) and c[key] not in txt:
            fails.append(f"contact {key} missing or altered: {c[key]}")

    # 4. Headline facts match. The graduation date is deliberately absent from
    #    builds made with --no-education-dates, so its presence is reported
    #    rather than required -- some employers ask US applicants to redact
    #    attendance and graduation dates as age proxies.
    edu = data["education"][0]
    if edu.get("gpa") and edu["gpa"] not in txt:
        fails.append(f"GPA missing or altered: {edu['gpa']}")
    if data["name"] not in txt:
        fails.append("candidate name missing")

    edu_dates = [e["date"] for e in data["education"] if e.get("date") and e["date"] in txt]
    if edu_dates:
        warns.append("education dates present (" + ", ".join(edu_dates) + ") -- "
                     "fine unless the employer asks US applicants to redact "
                     "age proxies; rebuild with --no-education-dates if so")
    else:
        print("    [info] education dates redacted (age-proxy compliance)")

    # 4b. Nothing else that identifies age or date of birth.
    for pat in (r"\bdate of birth\b", r"\bd\.?o\.?b\.?\b", r"\bage\s*[:=]\s*\d",
                r"\bborn\b"):
        if re.search(pat, low):
            fails.append(f"possible age/DOB identifier: matched /{pat}/")

    # 5. Honors: only what the school actually publishes.
    if "honor roll" in low:
        fails.append("'Honor Roll' present -- SNHU publishes only "
                     "President's List and Dean's List")

    # 6. Length proxy for the one-page rule. Calibrated against builds that
    #    were checked in Word: 3030 chars over 3 projects rendered on one
    #    page, 3350 over 4 did not.
    chars = sum(len(p) for p in txt.split("\n") if p.strip())
    projects = len([p for p in txt.split("\n") if p.endswith("Remote")])
    if chars > 3250:
        warns.append(f"{chars} chars over {projects} projects -- likely spills "
                     f"to page 2, verify in Word (--max-projects {projects-1})")
    elif chars > 3150:
        warns.append(f"{chars} chars over {projects} projects -- borderline, "
                     "verify in Word")

    # 7. Staged copy matches its master in Storage.
    master = os.path.join(STAGE_DIR, "Storage", name)
    if os.path.exists(master):
        if text_of(master) != txt:
            fails.append("staged copy differs from Storage master -- stale")
    else:
        warns.append("no master in Storage/")

    # 8. Staged copy is newer than the data it was built from.
    if os.path.getmtime(path) < os.path.getmtime(DATA_PATH):
        fails.append("older than resume_data.json -- rebuild and re-stage")

    # 9. Keyword coverage against this posting's brief.
    req = re.search(r"(\d{6,})", name)
    if req:
        hits = glob.glob(os.path.join(BRIEFS_DIR, f"*{req.group(1)}*.md"))
        if hits:
            import enrich
            desc = open(hits[0], encoding="utf-8", errors="replace").read().lower()
            _, missing = enrich.match_skills(desc, enrich.load_resume_skills())
            if missing:
                warns.append(f"posting asks for, resume lacks: {', '.join(missing)}")
    return fails, warns


def main():
    pattern = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    data = json.load(open(DATA_PATH, encoding="utf-8"))
    paths = [p for p in sorted(glob.glob(os.path.join(STAGE_DIR, "*.docx")))
             if pattern in os.path.basename(p).lower()
             and not os.path.basename(p).startswith("~$")]
    if not paths:
        sys.exit("No staged resumes matched.")

    total_fail = 0
    for p in paths:
        fails, warns = check(p, data)
        total_fail += len(fails)
        label = os.path.basename(p).replace("Nikolas_George_", "")[:58]
        print(f"\n{'FAIL' if fails else 'PASS'}  {label}")
        for f in fails:
            print(f"    [fail] {f}")
        for w in warns:
            print(f"    [warn] {w}")

    print(f"\n{len(paths)} checked, {total_fail} failure(s).")
    print("Warnings need your eyes; they are not automatic blockers.")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
