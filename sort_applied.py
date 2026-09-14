#!/usr/bin/env python3
"""Sort generated resumes into Applied/ and Rejected/ from a Simplify export.

Storage/ is an undifferentiated archive of every resume ever generated, which
makes it useless for answering "what did I actually send, and what came back".
This splits out the ones tied to a real submission.

Matching is by URL against each brief's recorded Apply link, then by requisition
id, then by an unambiguous company name. Anything it cannot match confidently is
reported rather than guessed at.

    py sort_applied.py <simplify.csv> [--apply]
"""
import csv
import glob
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "tailored", "Storage")
QUOTA = os.path.join(STORE, "_quota_blocked")
APPLIED = os.path.join(BASE, "tailored", "Applied")
REJECTED = os.path.join(BASE, "tailored", "Rejected")

# Outcomes the Simplify export does not carry. Keyed by brief stem fragment.
KNOWN_REJECTED = {
    "TikTok-Software-Engineer-Intern-Effects-Performance": "declined 2026-08-06",
}
KNOWN_APPLIED = {
    "TikTok-Software-Engineer-Intern-Trust-and-Safety": "2026-08-05",
}


def norm(u):
    u = (u or "").split("?")[0].rstrip("/").lower()
    return re.sub(r"/(apply|application|detail)$", "", u)


def req_ids(url):
    out = set(re.findall(r"\d{5,}", url or ""))
    out |= {m.upper() for m in re.findall(r"\b(?:R|RQ|REQ)[-_]?\d{4,}\b", url or "", re.I)}
    return out


def slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def brief_apply_urls():
    out = {}
    for b in glob.glob(os.path.join(BASE, "briefs", "*.md")):
        head = open(b, encoding="utf-8", errors="replace").read(2000)
        m = re.search(r"^\*\*Apply:\*\*\s*(\S+)", head, re.M)
        u = norm(m.group(1)) if m else ""
        # Briefs that are not real postings (the general resume) record "n/a"
        # here. Left as-is it is a short truthy string, and the substring test
        # below matches it inside any URL that happens to contain "n/a".
        if u in ("", "n/a", "none", "-"):
            u = ""
        out[os.path.splitext(os.path.basename(b))[0]] = u
    return out


def resume_files():
    """stem -> list of files (a stem may have both .docx and .pdf)."""
    out = {}
    for d in (STORE, QUOTA):
        for p in glob.glob(os.path.join(d, "*")):
            if os.path.isdir(p):
                continue
            name = os.path.basename(p)
            stem = re.sub(r"^Nikolas_George_", "", os.path.splitext(name)[0])
            out.setdefault(stem, []).append(p)
    return out


def find(row, briefs, files):
    url, comp = norm(row["Job URL"]), slug(row["Company Name"])
    for stem, burl in briefs.items():
        if burl and len(burl) > 20 and (
                burl == url or (len(url) > 30 and (url in burl or burl in url))):
            if stem in files:
                return stem, "url"
    ids = req_ids(row["Job URL"])
    if ids:
        for stem in files:
            if any(i in stem.upper() for i in ids):
                return stem, "req id"
    if comp:
        cands = [s for s in files if slug(s.split("-Software")[0]).startswith(comp[:10])]
        if len(cands) == 1:
            return cands[0], "company"
    return None, None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    csv_path, do_move = sys.argv[1], "--apply" in sys.argv
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))
            if (r["Status"] or "").strip().upper() == "APPLIED"]

    briefs, files = brief_apply_urls(), resume_files()
    plan, misses = {}, []

    for r in rows:
        stem, how = find(r, briefs, files)
        if stem:
            plan[stem] = (APPLIED, f"{r['Company Name']} | applied {r['Applied Date']} | matched by {how}")
        else:
            misses.append((r["Company Name"], r["Applied Date"]))

    for frag, when in KNOWN_APPLIED.items():
        for stem in files:
            if frag in stem:
                plan[stem] = (APPLIED, f"applied {when} (not in export)")
    for frag, why in KNOWN_REJECTED.items():
        for stem in files:
            if frag in stem:
                plan[stem] = (REJECTED, why)

    print(f"{len(rows)} APPLIED rows | {len(plan)} resumes to move | "
          f"{len(misses)} applications with no generated resume\n")
    for stem, (dest, why) in sorted(plan.items()):
        print(f"  -> {os.path.basename(dest):<8} {stem[:58]:<58} {why}")

    if not do_move:
        print("\nDry run. Re-run with --apply to move.")
        return

    for d in (APPLIED, REJECTED):
        os.makedirs(d, exist_ok=True)
    manifest = []
    moved = 0
    for stem, (dest, why) in plan.items():
        for src in files[stem]:
            tgt = os.path.join(dest, os.path.basename(src))
            if os.path.abspath(src) == os.path.abspath(tgt):
                continue
            shutil.move(src, tgt)
            moved += 1
        manifest.append((os.path.basename(dest), stem, why))

    with open(os.path.join(BASE, "tailored", "applied_manifest.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["folder", "resume", "note"])
        w.writerows(sorted(manifest))

    print(f"\nMoved {moved} file(s). Manifest: tailored/applied_manifest.csv")
    print("Applications with no generated resume (applied outside the pipeline):")
    for c, d in misses:
        print(f"  {d}  {c}")


if __name__ == "__main__":
    main()
