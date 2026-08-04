#!/usr/bin/env python3
"""
Records which applications were actually SUBMITTED.

The rest of the pipeline tracks what was *found*. Nothing tracked what was
*sent* -- so there was no way to answer "did I already apply here?" a week
later, and no way for the digest to stop re-suggesting a posting you've
already done.

Submission can't be detected reliably (it happens in a browser tab that gets
closed, and confirmation emails aren't visible here), so this is deliberately
a manual log. One command per application.

Usage:
    py applied.py appian                    mark as submitted today
    py applied.py appian --date 2026-07-30  backdate it
    py applied.py --list                    everything submitted so far
    py applied.py --pending                 APPLY briefs not yet submitted
    py applied.py appian --note "referred by X"
    py applied.py appian --status rejected  update outcome later
"""
import argparse
import json
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPLIED_PATH = os.path.join(BASE_DIR, "applied.json")
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")
ENRICHED_PATH = os.path.join(BASE_DIR, "enriched.json")

VALID_STATUS = ["submitted", "screening", "interview", "offer", "rejected", "ghosted"]


def load():
    if os.path.exists(APPLIED_PATH):
        with open(APPLIED_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(d):
    with open(APPLIED_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def briefs_by_verdict(verdict=None):
    out = {}
    try:
        enr = json.load(open(ENRICHED_PATH, encoding="utf-8"))
    except Exception:
        return out
    for v in enr.values():
        if v.get("status") != "ok" or not v.get("brief"):
            continue
        if verdict and v.get("verdict") != verdict:
            continue
        out[os.path.splitext(v["brief"])[0]] = v
    return out


def resolve(pattern, applied):
    """Match a pattern against briefs first, then against already-logged keys."""
    all_briefs = briefs_by_verdict()
    hits = [k for k in all_briefs if pattern.lower() in k.lower()]
    if not hits:
        hits = [k for k in applied if pattern.lower() in k.lower()]
    if not hits:
        print(f"Nothing matches '{pattern}'. Try `py applied.py --pending`.")
        return None
    if len(hits) > 1:
        print(f"'{pattern}' matches {len(hits)} postings -- be more specific:")
        for h in sorted(hits):
            print(f"  {h}")
        return None
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="?", help="company or posting fragment, e.g. appian")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--note", help="free-text note, e.g. who referred you")
    ap.add_argument("--status", choices=VALID_STATUS, help="update outcome")
    ap.add_argument("--list", action="store_true", help="show everything submitted")
    ap.add_argument("--pending", action="store_true", help="APPLY briefs not yet submitted")
    args = ap.parse_args()

    applied = load()

    if args.list:
        if not applied:
            print("Nothing logged yet.")
            return
        print(f"{len(applied)} application(s) submitted:\n")
        for k, v in sorted(applied.items(), key=lambda x: x[1].get("date", "")):
            line = f"  {v.get('date','?')}  [{v.get('status','submitted'):>9}]  {v.get('company') or k}"
            print(line)
            if v.get("note"):
                print(f"{'':>13}   note: {v['note']}")
        return

    if args.pending:
        todo = briefs_by_verdict("APPLY")
        left = {k: v for k, v in todo.items() if k not in applied}
        if not left:
            print("Nothing pending -- every APPLY posting has been submitted.")
            return
        print(f"{len(left)} APPLY posting(s) not yet submitted:\n")
        for k, v in sorted(left.items()):
            print(f"  {v.get('company')} — {v.get('title')}")
            print(f"    py tailor.py --stage {(v.get('company') or '').split()[0].lower()}")
        return

    if not args.pattern:
        ap.error("give a pattern (e.g. `py applied.py appian`), or use --list / --pending")

    key = resolve(args.pattern, applied)
    if not key:
        sys.exit(1)

    meta = briefs_by_verdict().get(key, {})
    entry = applied.get(key, {})
    entry.setdefault("company", meta.get("company"))
    entry.setdefault("title", meta.get("title"))
    entry.setdefault("brief", key + ".md")
    entry["date"] = args.date or entry.get("date") or date.today().isoformat()
    entry["status"] = args.status or entry.get("status") or "submitted"
    if args.note:
        entry["note"] = args.note

    was_new = key not in applied
    applied[key] = entry
    save(applied)

    verb = "Logged" if was_new else "Updated"
    print(f"{verb}: {entry.get('company')} — {entry.get('title')}")
    print(f"  date:   {entry['date']}")
    print(f"  status: {entry['status']}")
    if entry.get("note"):
        print(f"  note:   {entry['note']}")
    print(f"\n{len(applied)} total logged. `py applied.py --pending` for what's left.")


if __name__ == "__main__":
    main()
