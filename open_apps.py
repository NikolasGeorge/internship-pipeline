#!/usr/bin/env python3
"""
Opens application pages in the default browser for postings worth applying to.

Two guards, both learned the hard way:
  - Each posting is opened ONCE. An "opened" log means the twice-daily
    scheduled run doesn't reopen the same ten tabs every twelve hours.
  - A cap on tabs per run, so a busy September morning doesn't open thirty.

Skips anything already submitted (applied.json) and anything not marked APPLY.

Usage:
    py open_apps.py                  open pending APPLY postings (cap 3)
    py open_apps.py --max 10         raise the cap
    py open_apps.py --new-only       only postings never opened before
    py open_apps.py --dry-run        show what would open, open nothing
    py open_apps.py --reset          forget the opened log
"""
import argparse
import json
import os
import re
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENRICHED_PATH = os.path.join(BASE_DIR, "enriched.json")
APPLIED_PATH = os.path.join(BASE_DIR, "applied.json")
OPENED_PATH = os.path.join(BASE_DIR, "opened.json")
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")
STORAGE_DIR = os.path.join(BASE_DIR, "tailored", "Storage")
STAGE_DIR = os.path.join(BASE_DIR, "tailored")
RESUME_DATA = os.path.join(BASE_DIR, "resume_data.json")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def resume_prefix():
    """Prefix generated resumes carry; read from resume_data.json."""
    try:
        with open(RESUME_DATA, encoding="utf-8") as f:
            name = json.load(f).get("name", "Resume")
    except Exception:
        name = "Resume"
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Resume"


def quota_blocked_company(company):
    """Don't open tabs for employers whose application allowance is spent."""
    from datetime import date
    cfg = load(os.path.join(BASE_DIR, "config.json"), {})
    today = date.today().isoformat()
    for rule in cfg.get("quota_exhausted", []):
        if rule.get("until") and rule["until"] < today:
            continue
        if any(m.lower() in (company or "").lower() for m in rule.get("match", [])):
            return True
    return False


def apply_url(brief_name):
    """The Apply link recorded at the top of each brief."""
    p = os.path.join(BRIEFS_DIR, brief_name)
    try:
        head = open(p, encoding="utf-8").read(1500)
    except Exception:
        return None
    m = re.search(r"^\*\*Apply:\*\*\s*(\S+)", head, re.M)
    return m.group(1) if m else None


def stage_resume(brief_name):
    """Put this posting's resume alone in tailored/ so the file picker is trivial."""
    import shutil
    stem = os.path.splitext(brief_name)[0]
    src = os.path.join(STORAGE_DIR, f"{resume_prefix()}_{stem}.docx")
    if not os.path.exists(src):
        return None
    for f in os.listdir(STAGE_DIR):
        fp = os.path.join(STAGE_DIR, f)
        if os.path.isfile(fp) and f.endswith(".docx"):
            os.remove(fp)
    dst = os.path.join(STAGE_DIR, os.path.basename(src))
    shutil.copy2(src, dst)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3, help="tabs to open per run (default 3)")
    ap.add_argument("--new-only", action="store_true",
                    help="only postings never opened before (used by the scheduled run)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true", help="clear the opened log")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(OPENED_PATH):
            os.remove(OPENED_PATH)
        print("Opened log cleared. Every pending posting is openable again.")
        return

    enriched = load(ENRICHED_PATH, {})
    applied = load(APPLIED_PATH, {})
    opened = set(load(OPENED_PATH, []))
    applied_briefs = {v.get("brief") for v in applied.values()}

    queue = []
    for v in enriched.values():
        if v.get("status") != "ok" or v.get("verdict") != "APPLY":
            continue
        brief = v.get("brief")
        if not brief or brief in applied_briefs:
            continue
        if args.new_only and brief in opened:
            continue
        if quota_blocked_company(v.get("company")):
            continue
        url = apply_url(brief)
        if url:
            queue.append((v.get("company"), v.get("title"), url, brief))

    if not queue:
        print("Nothing to open." if not args.new_only
              else "No newly-found APPLY postings since last time.")
        return

    queue.sort(key=lambda r: (r[0] or ""))
    batch, held = queue[:args.max], queue[args.max:]

    print(f"{len(queue)} pending; opening {len(batch)}"
          + (f" (holding {len(held)} for next time)" if held else "") + "\n")

    for company, title, url, brief in batch:
        print(f"  {company} — {title}")
        print(f"    {url}")
        if not args.dry_run:
            webbrowser.open_new_tab(url)
            opened.add(brief)

    # Staging only makes sense when there's one obvious answer.
    if len(batch) == 1 and not args.dry_run:
        staged = stage_resume(batch[0][3])
        if staged:
            print(f"\n  Staged resume: {os.path.basename(staged)}")
    elif len(batch) > 1:
        print(f"\n  {len(batch)} tabs open, so no resume staged — the picker can't")
        print("  tell them apart. Stage per application:  py tailor.py --stage <company>")

    if not args.dry_run:
        with open(OPENED_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(opened), f, indent=2)

    print("\nNothing was submitted. Review each brief before applying.")


if __name__ == "__main__":
    main()
