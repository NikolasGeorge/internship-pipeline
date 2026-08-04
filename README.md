# Internship Pipeline

Automated tooling for a software internship search. It finds postings, fetches
the **real job description** from each company's applicant tracking system,
screens them against hard disqualifiers, and generates a resume tailored to
each one.

Stdlib-only Python except for `python-docx`. Runs on a schedule.

**It does not submit applications.** See [Scope](#scope).

---

## Why it exists

[SimplifyJobs/Summer2027-Internships][repo] publishes a machine-readable
`listings.json` — thousands of postings with company, title, location, and a
link. It does **not** include the job description.

That turns out to matter enormously. Ranking postings on company + title +
date is ranking them blind:

> Three postings appeared from the same company, same title, same day. All
> three scored identically. Reading the actual descriptions showed one
> required an **active TS/SCI clearance on day one** — unobtainable — one
> wanted a **Mechanical Engineering** degree, and one was a genuinely strong
> match 25 minutes from my house.

`enrich.py` exists to close that gap.

[repo]: https://github.com/SimplifyJobs/Summer2027-Internships

---

## Pipeline

```
watch.py     listings.json -> filter, score, dedupe          -> tracker.md
enrich.py    fetch real descriptions from the ATS API        -> briefs/
             screen for disqualifiers, assign a verdict         DIGEST.md
tailor.py    build a resume per posting from resume_data.json-> tailored/
open_apps.py open application pages worth acting on
applied.py   record what was actually submitted              -> applied.json
```

`DIGEST.md` is the entry point after a run: everything currently actionable,
grouped APPLY / REVIEW / SKIP, with the brief and resume path for each.

## Fetching descriptions

Each ATS exposes a public JSON API, so no browser or scraping is involved:

| ATS | Endpoint |
|---|---|
| Workday | `/wday/cxs/<tenant>/<site>/job/<path>` |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/<org>` |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/<c>/postings/<id>` |

Anything else falls back to an HTML fetch, and if that yields nothing (Workday
and Ashby render client-side) the posting is surfaced as "needs a manual look"
rather than silently dropped.

The Greenhouse `questions=true` parameter returns the **application form
fields**, not just the description. That matters: gating conditions often
appear only there. One posting read like an ordinary internship but carried a
required question — *"Are you registered to attend \[conference\] 2026?"* —
making it a conference talent pool rather than an open req.

## Screening

`HARD_DISQUALIFIERS` in `enrich.py` is a list of `(name, regex, explanation)`.
A match downgrades the posting and writes the explanation into its brief, so
the output says *why* rather than just assigning a number.

Verdicts:

- **APPLY** — nothing disqualifying found
- **REVIEW** — something to read first, e.g. a degree field that doesn't match
- **SKIP** — a hard disqualifier

A verdict is a filter on wasted effort, not a decision. The brief carries the
full description so you can disagree with it.

## Tailoring

`tailor.py` reorders — it does not write.

- Projects are ranked by keyword overlap with the real description
- Skills are reordered so languages the posting names appear first
- Bullet text is emitted **verbatim** from `resume_data.json`

If a posting wants something the resume doesn't have, that gap is reported in
the brief rather than invented into the document. A generator that can write
new claims onto a resume is a liability, not a feature.

---

## Setup

```bash
py -m pip install python-docx

cp config.example.json config.json
cp resume_data.example.json resume_data.json
# edit both
```

`resume_data.json` holds your real resume content and is gitignored, along
with everything else the tool generates about a live search.

```bash
py watch.py                 # find new postings
py enrich.py                # fetch descriptions + screen
py tailor.py --all-apply    # build resumes into tailored/Storage/
py tailor.py --stage <co>   # stage one resume for the file picker
py open_apps.py --max 1     # open a posting and stage its resume
py applied.py <co>          # log a submission
py applied.py --pending     # what's left
```

Schedule `run_watch.bat` (Windows Task Scheduler) or the equivalent cron entry
to run the first four automatically.

---

## Scope

The tool stops before the submit button, deliberately.

Applicant tracking systems detect automated submission, and the penalty lands
on the *candidate account* at that company — losing an account somewhere you
actually want to work is a bad trade for saving a few minutes. Account
creation, passwords, CAPTCHAs, file uploads, and the final click stay manual.

What's automated is the part that's genuinely mechanical: finding postings,
reading requirements, and preparing documents.
