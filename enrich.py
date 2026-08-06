#!/usr/bin/env python3
"""
Fetches real job descriptions for postings surfaced by watch.py, screens them
against hard disqualifiers, re-scores against actual requirement text, and
writes a per-posting brief.

This exists because listings.json carries NO description text — so watch.py's
score can only see company + title + date. That is how three RTX reqs all
scored 13 when one required an active TS/SCI clearance (unwinnable), one
wanted a Mechanical Engineering degree, and one was an excellent match.

Uses each ATS's public JSON API. No browser, no scraping, stdlib only.

Usage:
    py enrich.py                 enrich postings not yet enriched
    py enrich.py --all           re-enrich everything in tracker
    py enrich.py --url <URL>     enrich one specific posting URL
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")
ENRICHED_PATH = os.path.join(BASE_DIR, "enriched.json")
RESUME_PATH = os.path.join(BASE_DIR, "resume.md")
LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"

UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-job-search/1.0)"}
FETCH_DELAY = 1.5  # be polite to the APIs

# ---------------------------------------------------------------- disqualifiers
# Each rule: (name, regex, explanation). A hit means "do not spend time here."
HARD_DISQUALIFIERS = [
    (
        "active_clearance_required",
        r"(active and existing security clearance required|"
        r"active\s+(?:ts/sci|top secret|secret)\s+clearance\s+(?:is\s+)?required|"
        r"must (?:currently )?(?:possess|hold) an active[^.]{0,40}clearance|"
        r"current(?:ly)? active[^.]{0,30}clearance required)",
        "Requires an ALREADY-ACTIVE clearance on day one. A lapsed or lower-tier "
        "clearance does not satisfy this, and reinstatement generally requires "
        "under 24 months since last access. These reqs are filled by transfers "
        "from other cleared programs, not by students.",
    ),
    (
        "phd_required",
        r"(must be pursuing|currently enrolled in)[^.]{0,60}\b(ph\.?d|doctoral)\b",
        "Requires PhD enrollment.",
    ),
    (
        "us_citizenship_required",
        r"u\.?s\.? citizenship is required",
        "US citizenship required. Informational rather than disqualifying — "
        "flagged so it is never a surprise late in an application.",
    ),
]

# Degree-field mismatch: flag when a non-CS field is demanded and CS is absent.
NON_CS_DEGREE = re.compile(
    r"degree in\s+(mechanical|aerospace|electrical|civil|chemical|industrial)\b[^.]{0,80}",
    re.I,
)
CS_MENTION = re.compile(
    r"\b(computer science|software engineering|computer engineering|"
    r"applicable discipline|related (?:technical )?(?:field|discipline)|"
    r"stem)\b",
    re.I,
)

CLOSED_MARKERS = re.compile(
    r"(no longer accepting applications|this (?:job|position|requisition) is closed|"
    r"posting has expired|position has been filled)",
    re.I,
)

# --------------------------------------------------------------------- skills
SKILL_TERMS = [
    "python", "java", "c++", "c#", "javascript", "typescript", "sql", "rust",
    "assembly", "unity", ".net", "opengl", "git", "github", "gitlab", "agile",
    "scrum", "rest", "api", "linux", "unix", "docker", "kubernetes", "jenkins",
    "maven", "ci/cd", "devops", "devsecops", "unit test", "automated test",
    "regression", "machine learning", "ml", "data pipeline", "embedded",
    "arduino", "sensor", "real-time", "distributed", "react", "node",
    "angular", "vue", "mongodb", "matlab", "security", "owasp", "sdlc", "uml",
]


def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def strip_html(raw):
    if not raw:
        return ""
    # Unescape FIRST: Greenhouse returns entity-escaped markup (&lt;p&gt;), so
    # stripping tags before unescaping leaves the whole document intact.
    # Workday returns real tags plus double-encoded entities, which the second
    # unescape at the end handles.
    txt = html.unescape(raw)
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", txt, flags=re.I)
    txt = re.sub(r"<li[^>]*>", "\n- ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(html.unescape(txt))   # Workday double-encodes
    txt = txt.replace(" ", " ").replace("&#xa;", "\n")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return txt.strip()


# ------------------------------------------------------------- ATS detection
def detect_ats(url):
    u = url.lower()
    if "myworkdayjobs.com" in u:
        return "workday"
    if "greenhouse.io" in u:
        return "greenhouse"
    if "ashbyhq.com" in u:
        return "ashby"
    if "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "applytojob.com" in u:
        return "jazzhr"
    if "lever.co" in u:
        return "lever"
    return "unknown"


def fetch_workday(url):
    # https://<host>/<locale>/<site>/job/<path>  ->
    # https://<host>/wday/cxs/<tenant>/<site>/job/<path>
    m = re.match(r"https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/(.+)$", url)
    if not m:
        return None
    host, site, path = m.groups()
    tenant = host.split(".")[0]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/job/{path}"
    d = http_json(api)
    info = d.get("jobPostingInfo", {}) or {}
    return {
        "title": info.get("title"),
        "location": info.get("location"),
        "posted": info.get("postedOn"),
        "description": strip_html(info.get("jobDescription", "")),
        "apply_url": info.get("externalUrl") or url,
    }


def fetch_greenhouse(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?]+)(?:/jobs/|.*?gh_jid=)(\d+)", url)
    if not m:
        return None
    board, jid = m.groups()
    # questions=true also returns the APPLICATION FORM fields. Gating conditions
    # often live only there, never in the description -- Axon's "Are you
    # registered to attend RenderATL 2026?" is a required question on a posting
    # whose description reads like an ordinary internship.
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?questions=true")
    return {
        "title": d.get("title"),
        "location": (d.get("location") or {}).get("name"),
        "posted": d.get("updated_at"),
        "description": strip_html(d.get("content", "")),
        "apply_url": d.get("absolute_url") or url,
        "questions": [q.get("label", "").strip()
                      for q in (d.get("questions") or []) if q.get("label")],
    }


def fetch_ashby(url):
    m = re.search(r"ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    org, jid = m.groups()
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
    for j in d.get("jobs", []):
        if j.get("id") == jid or jid in (j.get("jobUrl") or ""):
            return {
                "title": j.get("title"),
                "location": j.get("location"),
                "posted": j.get("publishedAt"),
                "description": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
                "apply_url": j.get("applyUrl") or j.get("jobUrl") or url,
            }
    return None


def fetch_smartrecruiters(url):
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return None
    company, jid = m.groups()
    d = http_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{jid}")
    ad = d.get("jobAd", {}).get("sections", {})
    parts = [ad.get(k, {}).get("text", "") for k in
             ("jobDescription", "qualifications", "additionalInformation")]
    loc = d.get("location", {}) or {}
    return {
        "title": d.get("name"),
        "location": ", ".join(x for x in [loc.get("city"), loc.get("region")] if x),
        "posted": d.get("releasedDate"),
        "description": strip_html("\n\n".join(p for p in parts if p)),
        "apply_url": d.get("applyUrl") or url,
    }


def fetch_generic(url):
    """Last resort for ATSs without a JSON API (JazzHR, custom career sites).
    Pulls the raw page and strips tags. Works when the description is
    server-rendered; returns nothing useful for JS-only pages, which is the
    signal to open that one in the browser instead."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    body = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
    text = strip_html(body.group(1) if body else raw)
    # Collapse nav/footer noise: keep the longest contiguous block.
    blocks = [b.strip() for b in text.split("\n\n") if len(b.strip()) > 200]
    text = "\n\n".join(blocks) if blocks else text
    if len(text) < 400:
        return None
    return {"title": None, "location": None, "posted": None,
            "description": text, "apply_url": url}


FETCHERS = {
    "workday": fetch_workday,
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "jazzhr": fetch_generic,
    "lever": fetch_generic,
    "unknown": fetch_generic,
}


# -------------------------------------------------------------------- analysis
def resume_prefix():
    """Prefix generated resumes carry; read from resume_data.json."""
    try:
        with open(os.path.join(BASE_DIR, "resume_data.json"), encoding="utf-8") as f:
            name = json.load(f).get("name", "Resume")
    except Exception:
        name = "Resume"
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Resume"


def load_resume_skills():
    if not os.path.exists(RESUME_PATH):
        return set()
    text = open(RESUME_PATH, encoding="utf-8").read().lower()
    return {s for s in SKILL_TERMS if s in text}


def screen(desc):
    """Return (disqualifiers, warnings) found in the description text."""
    dq, warn = [], []
    low = desc.lower()

    for name, pattern, why in HARD_DISQUALIFIERS:
        if re.search(pattern, low, re.I):
            if name == "us_citizenship_required":
                warn.append((name, why))
            else:
                dq.append((name, why))

    if CLOSED_MARKERS.search(low):
        dq.append(("closed", "Posting appears closed / no longer accepting applications."))

    m = NON_CS_DEGREE.search(desc)
    if m and not CS_MENTION.search(desc):
        warn.append((
            "degree_field_mismatch",
            f"Names a non-CS degree field ({m.group(1).lower()}) and never mentions CS. "
            "Check whether the duties are actually software — RTX reqs carry this line "
            "as boilerplate — but treat a hard degree dropdown on the form as a stop sign.",
        ))
    return dq, warn


# Application-form questions that gate eligibility on something outside the
# candidate's control. These never appear in the job description.
QUESTION_GATES = [
    (
        "event_attendance_gate",
        r"(are you (?:registered|attending|signed up)[^?]{0,40}(?:to attend\s+)?[A-Z][\w ]{2,30}\s?20\d\d|"
        r"will you be attending[^?]{0,50}(?:conference|summit|expo|fair))",
        "Eligibility is tied to attending a specific event. If you're not "
        "registered, this is a conference talent pool rather than an open req — "
        "expect the application to go nowhere.",
    ),
    (
        "program_membership_gate",
        r"are you (?:a )?(?:current(?:ly)? )?(?:member|participant|scholar|fellow)[^?]{0,40}"
        r"(?:program|cohort|society|association)",
        "Restricted to members of a named program. Check you qualify before applying.",
    ),
]


def screen_questions(questions):
    """Flag gating conditions that live in the FORM rather than the description."""
    flags = []
    joined = "\n".join(questions)
    for name, pattern, why in QUESTION_GATES:
        m = re.search(pattern, joined, re.I)
        if m:
            flags.append((name, f'{why}\n\n  Question: "{m.group(0).strip()[:110]}"'))
    return flags


def match_skills(desc, resume_skills):
    low = desc.lower()
    wanted = {s for s in SKILL_TERMS if s in low}
    return sorted(wanted & resume_skills), sorted(wanted - resume_skills)


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:60]


def req_id(p, data):
    """Stable per-req suffix. Titles collide (RTX posts 3 identical ones), so a
    brief keyed on company+title alone silently overwrites the others."""
    m = re.search(r"_(\w{2,}\d{3,})(?:\?|$)", p.get("url", ""))
    if m:
        return m.group(1)
    m = re.search(r"/(\d{6,})(?:\?|/|$)", p.get("url", ""))
    if m:
        return m.group(1)
    return (p.get("id") or "")[:8]


def write_brief(p, data, dq, warn, have, missing):
    name = (f"{slug(p.get('company_name'))}-"
            f"{slug(data.get('title') or p.get('title'))}-"
            f"{req_id(p, data)}.md")
    path = os.path.join(BRIEFS_DIR, name)
    verdict = "SKIP" if dq else ("REVIEW" if warn else "APPLY")

    L = []
    L.append(f"# {p.get('company_name')} — {data.get('title') or p.get('title')}")
    L.append("")
    L.append(f"**Verdict:** {verdict}")
    L.append(f"**Location:** {data.get('location') or ', '.join(p.get('locations', []))}")
    L.append(f"**Posted:** {data.get('posted')}")
    L.append(f"**ATS:** {detect_ats(p.get('url',''))}")
    L.append(f"**Apply:** {data.get('apply_url') or p.get('url')}")
    L.append("")
    if dq:
        L.append("## Hard disqualifiers — do not spend time here")
        L.append("")
        for n, why in dq:
            L.append(f"- **{n}** — {why}")
        L.append("")
    if warn:
        L.append("## Flags — read before applying")
        L.append("")
        for n, why in warn:
            L.append(f"- **{n}** — {why}")
        L.append("")
    L.append("## Requirement keywords you already have")
    L.append("")
    L.append(", ".join(have) if have else "_none detected_")
    L.append("")
    L.append("## Requirement keywords you do NOT have")
    L.append("")
    L.append((", ".join(missing) if missing else "_none_") +
             "\n\n_Do not add any of these to the resume unless genuinely true._")
    L.append("")
    L.append("## Full description")
    L.append("")
    L.append(data.get("description", "").strip())
    L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path, verdict


def main():
    os.makedirs(BRIEFS_DIR, exist_ok=True)

    # Called last in the scheduled chain, after tailor.py has produced the
    # .docx files, so the digest can link them.
    if "--digest-only" in sys.argv:
        write_digest()
        print("Digest rebuilt: DIGEST.md")
        return

    resume_skills = load_resume_skills()

    enriched = {}
    if os.path.exists(ENRICHED_PATH):
        enriched = json.load(open(ENRICHED_PATH, encoding="utf-8"))

    seen_path = os.path.join(BASE_DIR, "seen.json")
    seen_ids = set(json.load(open(seen_path, encoding="utf-8"))) if os.path.exists(seen_path) else set()

    req = urllib.request.Request(LISTINGS_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        listings = json.loads(r.read().decode("utf-8"))

    if "--url" in sys.argv:
        target = sys.argv[sys.argv.index("--url") + 1]
        targets = [p for p in listings if p.get("url") == target]
        if not targets:
            targets = [{"company_name": "manual", "title": "manual", "url": target,
                        "id": "manual", "locations": []}]
    else:
        do_all = "--all" in sys.argv
        targets = [p for p in listings
                   if p.get("id") in seen_ids
                   and (do_all or p.get("id") not in enriched)]

    if not targets:
        print("Nothing to enrich. (Run watch.py first, or pass --all.)")
        return

    print(f"Enriching {len(targets)} posting(s)...\n")
    results = []
    for p in targets:
        url = p.get("url", "")
        ats = detect_ats(url)
        fetcher = FETCHERS.get(ats)
        if not fetcher:
            print(f"  [skip] {p.get('company_name')} — unsupported ATS: {ats}")
            enriched[p.get("id")] = {"ats": ats, "status": "unsupported"}
            continue
        data = None
        try:
            data = fetcher(url)
            time.sleep(FETCH_DELAY)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                print(f"  [closed/gone] {p.get('company_name')} — {p.get('title')}")
                enriched[p.get("id")] = {"ats": ats, "status": "closed/gone"}
                continue
            # Some tenants reject the standard API shape (Castleton returns 422).
            # Fall through to the generic HTML path rather than losing the posting.
            print(f"  [retry ] {p.get('company_name')} — {ats} API said {e.code}, trying HTML")
        except Exception as e:
            print(f"  [retry ] {p.get('company_name')} — {ats} API failed ({e}), trying HTML")

        if not data and fetcher is not fetch_generic:
            try:
                data = fetch_generic(url)
                time.sleep(FETCH_DELAY)
            except Exception as e:
                print(f"  [error ] {p.get('company_name')} — HTML fallback failed: {e}")
                enriched[p.get("id")] = {"ats": ats, "status": "fetch failed"}
                continue

        if not data or not data.get("description"):
            # Workday/Ashby render client-side, so the HTML fallback sees an
            # empty shell. Nothing more to try without a browser.
            print(f"  [manual] {p.get('company_name')} — {p.get('title')}")
            print("           no description via API or HTML; open in browser:")
            print(f"           {url}")
            enriched[p.get("id")] = {"ats": ats, "status": "needs manual fetch",
                                     "url": url, "company": p.get("company_name"),
                                     "title": p.get("title")}
            continue

        dq, warn = screen(data["description"])
        warn += screen_questions(data.get("questions") or [])
        have, missing = match_skills(data["description"], resume_skills)
        path, verdict = write_brief(p, data, dq, warn, have, missing)
        # The generic HTML fetcher can't parse a title; fall back to the
        # listing's own title so nothing ever displays as "None".
        title = data.get("title") or p.get("title")
        enriched[p.get("id")] = {
            "ats": ats, "status": "ok", "verdict": verdict,
            "brief": os.path.basename(path),
            "company": p.get("company_name"), "title": title,
        }
        results.append((verdict, p.get("company_name"), title, path))
        print(f"  [{verdict:>6}] {p.get('company_name')} — {title}")

    with open(ENRICHED_PATH, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2)

    print("\n" + "=" * 66)
    for v in ("APPLY", "REVIEW", "SKIP"):
        rows = [r for r in results if r[0] == v]
        if rows:
            print(f"\n{v} ({len(rows)}):")
            for _, comp, title, path in rows:
                print(f"  {comp} — {title}")
                print(f"    {os.path.relpath(path, BASE_DIR)}")
    print("\nBriefs written to briefs/. Nothing was submitted.")

    write_digest(results)



def quota_blocked():
    """Companies whose application allowance is spent.

    Some employers cap applications per recruitment cycle rather than per
    posting -- ByteDance and TikTok share a 2-application limit across the
    whole 2027 intern project. Surfacing 37 postings you cannot apply to is
    worse than surfacing none, so they are moved out of the actionable list.
    """
    from datetime import date
    try:
        cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
    except Exception:
        return []
    out = []
    today = date.today().isoformat()
    for rule in cfg.get("quota_exhausted", []):
        if rule.get("until") and rule["until"] < today:
            continue          # window has passed; the cap no longer applies
        out.append(rule)
    return out


def quota_rule_for(company):
    for rule in quota_blocked():
        if any(m.lower() in (company or "").lower() for m in rule.get("match", [])):
            return rule
    return None


def write_digest(_unused=None):
    """A single file that answers 'what should I do next' without opening every
    brief. Built from enriched.json rather than one run's results, so it shows
    the whole current backlog and can be regenerated after tailor.py has built
    the resumes. tracker.md keeps the append-only history."""
    from datetime import datetime, timezone
    path = os.path.join(BASE_DIR, "DIGEST.md")
    try:
        enr = json.load(open(ENRICHED_PATH, encoding="utf-8"))
    except Exception:
        enr = {}

    # Already-submitted postings drop out of the digest -- re-suggesting them
    # is how you end up applying to the same req twice.
    try:
        applied = json.load(open(os.path.join(BASE_DIR, "applied.json"), encoding="utf-8"))
    except Exception:
        applied = {}
    applied_briefs = {v.get("brief") for v in applied.values()}

    rows, done, blocked = [], [], []
    for v in enr.values():
        if v.get("status") != "ok" or not v.get("brief"):
            continue
        if v["brief"] in applied_briefs:
            done.append(v)
            continue
        rule = quota_rule_for(v.get("company"))
        if rule:
            blocked.append((v, rule))
            continue
        rows.append((v.get("verdict", "REVIEW"), v.get("company"), v.get("title"),
                     os.path.join(BRIEFS_DIR, v["brief"])))
    if not rows:
        return
    order = {"APPLY": 0, "REVIEW": 1, "SKIP": 2}
    rows.sort(key=lambda r: (order.get(r[0], 9), (r[1] or "")))

    L = [f"# Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
         "",
         f"{sum(1 for r in rows if r[0]=='APPLY')} to apply · "
         f"{sum(1 for r in rows if r[0]=='REVIEW')} to review · "
         f"{sum(1 for r in rows if r[0]=='SKIP')} to skip · "
         f"**{len(done)} already submitted**",
         ""]
    if blocked:
        by_rule = {}
        for v, rule in blocked:
            by_rule.setdefault(rule["note"], []).append(v)
        for note, items in by_rule.items():
            L += [f"<details><summary>{len(items)} hidden — application quota reached</summary>",
                  "", f"_{note}_", ""]
            for v in sorted(items, key=lambda x: (x.get("company") or "")):
                L.append(f"- {v.get('company')} — {v.get('title')}")
            L += ["", "</details>", ""]
    if done:
        L += ["<details><summary>Already submitted — not shown below</summary>", ""]
        for v in sorted(done, key=lambda x: (x.get("company") or "")):
            L.append(f"- {v.get('company')} — {v.get('title')}")
        L += ["", "</details>", ""]
    for v, label in (("APPLY", "Apply"), ("REVIEW", "Read the flags first"), ("SKIP", "Skip")):
        sel = [r for r in rows if r[0] == v]
        if not sel:
            continue
        L += [f"## {label}", ""]
        for _, comp, title, bp in sel:
            stem = os.path.splitext(os.path.basename(bp))[0]
            res = f"tailored/{resume_prefix()}_{stem}.docx"
            L.append(f"- **{comp}** — {title}")
            L.append(f"  - brief: `briefs/{os.path.basename(bp)}`")
            if os.path.exists(os.path.join(BASE_DIR, res.replace("/", os.sep))):
                L.append(f"  - resume: `{res}`")
        L.append("")
    # Postings no automated path could read -- surfaced so they aren't lost.
    try:
        enr = json.load(open(ENRICHED_PATH, encoding="utf-8"))
    except Exception:
        enr = {}
    manual = [v for v in enr.values() if v.get("status") == "needs manual fetch"]
    if manual:
        L += ["## Needs a manual look", "",
              "_Client-side-rendered postings the API and HTML paths can't read._", ""]
        for m in manual:
            L.append(f"- **{m.get('company')}** — {m.get('title')}")
            L.append(f"  - {m.get('url')}")
        L.append("")

    L += ["---", "",
          "Nothing here was submitted. Open the brief, check the verdict, then "
          "apply manually with the matching resume."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"Digest: {os.path.relpath(path, BASE_DIR)}")


if __name__ == "__main__":
    main()
