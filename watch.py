#!/usr/bin/env python3
"""
Internship posting watcher for SimplifyJobs/Summer2027-Internships.

Reads listings.json directly from the repo's dev branch (the machine-readable
source the README table is generated from), filters/scores postings, diffs
against a local seen-postings cache so only new listings surface, and appends
results to a tracker file. Does NOT submit any applications.

Usage:
    py watch.py                  run once, print + log new postings
    py watch.py --dump           print full scored list (ignore seen cache)

Config lives in config.json (created with defaults on first run).
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SEEN_PATH = os.path.join(BASE_DIR, "seen.json")
FAANG_PATH = os.path.join(BASE_DIR, "faang_plus.json")
TRACKER_PATH = os.path.join(BASE_DIR, "tracker.md")

DEFAULT_CONFIG = {
    "locations": [],
    "max_age_days": 21,
    "title_keywords": [
        "software", "swe", "backend", "back-end", "back end",
        "full stack", "full-stack", "frontend", "front-end", "front end",
        "systems engineer", "platform engineer", "site reliability",
        "infrastructure", "devops",
    ],
    "categories": ["Software", "Software Engineering"],
    "terms_allow": ["Summer 2027", "N/A"],
    "discord_webhook": "",
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print(f"Created default config at {CONFIG_PATH} — edit 'locations' before your first real run.")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def load_faang():
    with open(FAANG_PATH, encoding="utf-8") as f:
        return set(name.lower() for name in json.load(f))


def fetch_listings():
    req = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "internship-watcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def matches_location(posting, wanted_locations):
    if not wanted_locations:
        return True
    locs = [l.lower() for l in posting.get("locations", [])]
    if not locs:
        return True  # unspecified location — don't filter out
    wanted = [w.lower() for w in wanted_locations]
    for loc in locs:
        for w in wanted:
            if w.startswith(", "):
                # state-code style match: require the code to end at a boundary
                # (comma or end of string), not just be a substring (avoids "ca" in "canada")
                if re.search(re.escape(w) + r"(,|$)", loc):
                    return True
            elif w in loc:
                return True
    return False


def matches_title(title, keywords):
    t = title.lower()
    return any(kw in t for kw in keywords)


def matches_terms(terms, allowed):
    if not terms:
        return True
    return any(t in allowed for t in terms) or "N/A" in terms


def score_posting(posting):
    """Heuristic fit score. Weighted toward defense/gov and mid-size employers,
    where a security-clearance background differentiates a candidate instead of
    being one line among thousands of similar resumes. Adjust to taste."""
    score = 0
    title = posting.get("title", "").lower()
    company = posting.get("company_name", "").lower()

    if any(k in title for k in ["software engineer", "swe"]):
        score += 5
    if any(k in title for k in ["backend", "back-end", "systems", "platform", "infrastructure"]):
        score += 3
    if "security" in title or "clearance" in title:
        score += 4
    defense_gov = ["rtx", "raytheon", "leidos", "lockheed", "northrop", "boeing",
                   "general dynamics", "l3harris", "booz allen", "saic", "caci",
                   "navy", "navsea", "darpa", "mitre", "sandia", "national lab"]
    if any(k in company for k in defense_gov):
        score += 6
    if posting.get("sponsorship") == "Sponsorship Not Offered":
        score -= 1
    active_days = (time.time() - posting.get("date_posted", time.time())) / 86400
    if active_days < 3:
        score += 2
    return score


def main():
    cfg = load_config()
    faang = load_faang()
    seen = load_seen()
    dump_all = "--dump" in sys.argv

    listings = fetch_listings()

    now = time.time()
    max_age = cfg["max_age_days"] * 86400
    categories_allow = set(cfg["categories"])

    candidates = []
    for p in listings:
        if not p.get("active", False) or not p.get("is_visible", True):
            continue
        if p.get("category") not in categories_allow:
            continue
        if not matches_terms(p.get("terms", []), cfg["terms_allow"]):
            continue
        if not matches_title(p.get("title", ""), cfg["title_keywords"]):
            continue
        if not matches_location(p, cfg["locations"]):
            continue
        posted = p.get("date_posted", 0)
        if posted and (now - posted) > max_age:
            continue
        candidates.append(p)

    for p in candidates:
        p["_is_faang"] = p.get("company_name", "").strip().lower() in faang
        p["_score"] = score_posting(p)

    faang_hits = sorted([p for p in candidates if p["_is_faang"]], key=lambda p: -p["_score"])
    scored_fits = sorted([p for p in candidates if not p["_is_faang"]], key=lambda p: -p["_score"])

    new_ids = [p["id"] for p in candidates if p["id"] not in seen]

    print(f"Fetched {len(listings)} total listings, {len(candidates)} match filters.")
    print(f"FAANG+ postings: {len(faang_hits)}   Other scored fits: {len(scored_fits)}")
    print(f"New since last run: {len(new_ids)}\n")

    to_report = candidates if dump_all else [p for p in candidates if p["id"] in new_ids]

    if not to_report:
        print("No new postings." if not dump_all else "No postings match current filters.")
    else:
        print("=" * 70)
        print("FAANG+ (fire emoji)")
        print("=" * 70)
        for p in [x for x in to_report if x["_is_faang"]]:
            print(f"  {p['company_name']} — {p['title']} [{', '.join(p.get('locations', []) ) or 'N/A'}]")
            print(f"    {p['url']}")
        print()
        print("=" * 70)
        print("Best realistic fits (scored)")
        print("=" * 70)
        for p in [x for x in to_report if not x["_is_faang"]]:
            print(f"  ({p['_score']:>2}) {p['company_name']} — {p['title']} [{', '.join(p.get('locations', [])) or 'N/A'}]")
            print(f"    {p['url']}")

    if not dump_all:
        with open(TRACKER_PATH, "a", encoding="utf-8") as f:
            if to_report:
                f.write(f"\n## Run: {datetime.now(timezone.utc).isoformat()}\n\n")
                for p in to_report:
                    tag = "🔥 FAANG+" if p["_is_faang"] else f"score={p['_score']}"
                    f.write(f"- [ ] **{p['company_name']}** — {p['title']} ({tag}) — {', '.join(p.get('locations', [])) or 'N/A'}\n")
                    f.write(f"  {p['url']}\n")
        seen.update(p["id"] for p in candidates)
        save_seen(seen)

    webhook = cfg.get("discord_webhook")
    if webhook and to_report:
        lines = []
        for p in to_report:
            tag = "🔥" if p["_is_faang"] else f"({p['_score']})"
            lines.append(f"{tag} **{p['company_name']}** — {p['title']}\n{p['url']}")
        content = "\n\n".join(lines)[:1900]
        data = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"Discord webhook failed: {e}")


if __name__ == "__main__":
    main()
