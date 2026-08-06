"""Description parsing, screening, and quota rules in enrich.py.

Nothing here touches the network. The fetch_* functions are covered only for
their URL-parsing half, which is the part that actually breaks when an ATS
changes a path format.
"""
import enrich


# ------------------------------------------------------------------ strip_html
class TestStripHtml:
    def test_empty_input(self):
        assert enrich.strip_html("") == ""
        assert enrich.strip_html(None) == ""

    def test_tags_are_removed(self):
        assert enrich.strip_html("<p>Hello <b>world</b></p>").strip() == "Hello world"

    def test_entity_escaped_markup_is_unescaped_before_stripping(self):
        # Greenhouse returns the whole document entity-escaped. Stripping tags
        # first would leave the markup intact, so the order matters.
        out = enrich.strip_html("&lt;p&gt;Backend intern&lt;/p&gt;")
        assert "<p>" not in out
        assert "Backend intern" in out

    def test_workday_double_encoding_is_resolved(self):
        assert "&amp;" not in enrich.strip_html("R&amp;amp;D team")
        assert "R&D team" in enrich.strip_html("R&amp;amp;D team")

    def test_script_and_style_blocks_are_dropped(self):
        out = enrich.strip_html("<script>var x = 1;</script><p>Real text</p>")
        assert "var x" not in out
        assert "Real text" in out

    def test_list_items_become_dashed_lines(self):
        out = enrich.strip_html("<ul><li>Python</li><li>Java</li></ul>")
        assert "- Python" in out
        assert "- Java" in out

    def test_breaks_become_newlines(self):
        assert "\n" in enrich.strip_html("Line one<br>Line two")

    def test_runs_of_whitespace_collapse(self):
        assert enrich.strip_html("<p>too     many     spaces</p>") == "too many spaces"

    def test_blank_line_runs_collapse_to_one(self):
        assert "\n\n\n" not in enrich.strip_html("<p>a</p><p></p><p></p><p></p><p>b</p>")


# ------------------------------------------------------------------ detect_ats
class TestDetectAts:
    def test_workday(self):
        assert enrich.detect_ats(
            "https://rtx.wd1.myworkdayjobs.com/en-US/REC/job/Intern_01863012"
        ) == "workday"

    def test_greenhouse(self):
        assert enrich.detect_ats(
            "https://boards.greenhouse.io/acme/jobs/4567") == "greenhouse"

    def test_ashby(self):
        assert enrich.detect_ats("https://jobs.ashbyhq.com/acme/uuid") == "ashby"

    def test_smartrecruiters(self):
        assert enrich.detect_ats(
            "https://jobs.smartrecruiters.com/Acme/744000") == "smartrecruiters"

    def test_jazzhr(self):
        assert enrich.detect_ats("https://acme.applytojob.com/apply/abc") == "jazzhr"

    def test_lever(self):
        assert enrich.detect_ats("https://jobs.lever.co/acme/uuid") == "lever"

    def test_url_case_is_ignored(self):
        assert enrich.detect_ats(
            "https://ACME.MyWorkdayJobs.com/en-US/x/job/y") == "workday"

    def test_unrecognised_host(self):
        assert enrich.detect_ats("https://careers.example.com/job/1") == "unknown"


# ----------------------------------------------------- ATS URL parsing (no network)
class TestFetcherUrlParsing:
    def test_workday_rejects_a_url_without_a_job_path(self):
        assert enrich.fetch_workday("https://rtx.wd1.myworkdayjobs.com/en-US/REC") is None

    def test_greenhouse_rejects_a_url_without_a_job_id(self):
        assert enrich.fetch_greenhouse("https://boards.greenhouse.io/acme") is None

    def test_ashby_rejects_a_url_without_a_uuid(self):
        assert enrich.fetch_ashby("https://jobs.ashbyhq.com/acme") is None

    def test_smartrecruiters_rejects_a_url_without_a_posting_id(self):
        assert enrich.fetch_smartrecruiters("https://jobs.smartrecruiters.com/Acme") is None


# ---------------------------------------------------------------------- screen
class TestScreen:
    def test_clean_description_is_clean(self):
        dq, warn = enrich.screen("We are hiring a software engineering intern.")
        assert dq == []
        assert warn == []

    def test_active_clearance_disqualifies(self):
        dq, _ = enrich.screen("An active TS/SCI clearance is required for this role.")
        assert [n for n, _ in dq] == ["active_clearance_required"]

    def test_must_hold_an_active_clearance_phrasing(self):
        dq, _ = enrich.screen(
            "Candidates must currently possess an active Department of Defense clearance.")
        assert [n for n, _ in dq] == ["active_clearance_required"]

    def test_ability_to_obtain_a_clearance_is_not_a_disqualifier(self):
        # The candidate held a Secret clearance that has since lapsed, so
        # "must be able to obtain" reqs are exactly the ones worth applying to.
        dq, _ = enrich.screen("Must be able to obtain a security clearance.")
        assert dq == []

    def test_phd_requirement_disqualifies(self):
        dq, _ = enrich.screen("Must be pursuing a PhD in a related field.")
        assert [n for n, _ in dq] == ["phd_required"]

    def test_citizenship_is_a_warning_not_a_disqualifier(self):
        dq, warn = enrich.screen("U.S. citizenship is required for this position.")
        assert dq == []
        assert [n for n, _ in warn] == ["us_citizenship_required"]

    def test_closed_posting_is_disqualified(self):
        dq, _ = enrich.screen("This role is no longer accepting applications.")
        assert "closed" in [n for n, _ in dq]

    def test_non_cs_degree_without_cs_mention_warns(self):
        _, warn = enrich.screen("Requires a degree in Mechanical Engineering.")
        assert [n for n, _ in warn] == ["degree_field_mismatch"]

    def test_non_cs_degree_alongside_cs_does_not_warn(self):
        # RTX carries this as boilerplate: the same sentence names both, and
        # flagging it would bury the real mismatches.
        _, warn = enrich.screen(
            "Requires a degree in Mechanical Engineering, Computer Science, "
            "or a related technical field.")
        assert warn == []


# ------------------------------------------------------------- screen_questions
class TestScreenQuestions:
    def test_ordinary_questions_are_not_flagged(self):
        assert enrich.screen_questions(
            ["What is your expected graduation date?", "Preferred name"]) == []

    def test_event_attendance_gate_is_flagged(self):
        # A req whose description reads ordinary but whose form gates on
        # conference attendance is a talent pool, not an open position.
        flags = enrich.screen_questions(
            ["Are you registered to attend RenderATL 2026?"])
        assert [n for n, _ in flags] == ["event_attendance_gate"]

    def test_attending_a_conference_phrasing_is_flagged(self):
        flags = enrich.screen_questions(
            ["Will you be attending our annual developer conference?"])
        assert [n for n, _ in flags] == ["event_attendance_gate"]

    def test_program_membership_gate_is_flagged(self):
        flags = enrich.screen_questions(
            ["Are you a current member of the SHPE program?"])
        assert [n for n, _ in flags] == ["program_membership_gate"]

    def test_the_matched_question_is_quoted_back(self):
        flags = enrich.screen_questions(
            ["Are you registered to attend RenderATL 2026?"])
        assert "RenderATL" in flags[0][1]


# ---------------------------------------------------------------- match_skills
class TestMatchSkills:
    def test_splits_wanted_skills_into_have_and_missing(self):
        have, missing = enrich.match_skills(
            "Looking for Python and Kubernetes experience.", {"python", "java"})
        assert have == ["python"]
        assert missing == ["kubernetes"]

    def test_resume_skills_not_named_by_the_posting_are_ignored(self):
        have, missing = enrich.match_skills("Python only.", {"python", "java"})
        assert have == ["python"]
        assert "java" not in missing

    def test_description_case_is_ignored(self):
        have, _ = enrich.match_skills("PYTHON and DOCKER", {"python", "docker"})
        assert have == ["docker", "python"]

    def test_results_are_sorted(self):
        _, missing = enrich.match_skills("rust, docker, angular", set())
        assert missing == sorted(missing)


# ----------------------------------------------------------------------- slug
class TestSlug:
    def test_spaces_and_punctuation_become_single_hyphens(self):
        assert enrich.slug("Software Engineer, Intern") == "Software-Engineer-Intern"

    def test_leading_and_trailing_separators_are_trimmed(self):
        assert enrich.slug("  -- Backend --  ") == "Backend"

    def test_none_and_empty(self):
        assert enrich.slug(None) == ""
        assert enrich.slug("") == ""

    def test_length_is_capped(self):
        assert len(enrich.slug("x" * 200)) == 60


# --------------------------------------------------------------------- req_id
class TestReqId:
    def test_underscore_style_workday_req_number(self):
        # Titles collide -- RTX posts three identical ones -- so a brief keyed
        # on company+title alone silently overwrites the others.
        assert enrich.req_id(
            {"url": "https://rtx.wd1.myworkdayjobs.com/job/Intern_01863012"}, {}
        ) == "01863012"

    def test_req_number_before_a_query_string(self):
        # Simplify appends ?src=..., so the pattern has to terminate on the
        # query string as well as on end-of-string.
        assert enrich.req_id(
            {"url": "https://x.com/job/Software-Intern_R2026?src=simplify"}, {}
        ) == "R2026"

    def test_numeric_path_segment(self):
        assert enrich.req_id(
            {"url": "https://boards.greenhouse.io/acme/jobs/4567891"}, {}) == "4567891"

    def test_falls_back_to_a_truncated_posting_id(self):
        assert enrich.req_id(
            {"url": "https://example.com/careers", "id": "abcdefgh12345"}, {}
        ) == "abcdefgh"

    def test_no_url_and_no_id(self):
        assert enrich.req_id({}, {}) == ""

    def test_distinct_reqs_get_distinct_ids(self):
        a = enrich.req_id({"url": "https://x.com/job/Intern_01863012"}, {})
        b = enrich.req_id({"url": "https://x.com/job/Intern_01863013"}, {})
        assert a != b


# ------------------------------------------------------------------ quota rules
class TestQuotaRules:
    RULE = {"match": ["tiktok", "bytedance"], "until": "2999-12-31",
            "note": "Shared cap."}

    def test_no_config_means_no_blocks(self, config_dir):
        config_dir(enrich, {})
        assert enrich.quota_blocked() == []

    def test_an_active_rule_is_returned(self, config_dir):
        config_dir(enrich, {"quota_exhausted": [self.RULE]})
        assert enrich.quota_blocked() == [self.RULE]

    def test_an_expired_rule_is_dropped(self, config_dir):
        expired = dict(self.RULE, until="2000-01-01")
        config_dir(enrich, {"quota_exhausted": [expired]})
        assert enrich.quota_blocked() == []

    def test_a_rule_without_an_end_date_never_expires(self, config_dir):
        forever = {"match": ["tiktok"]}
        config_dir(enrich, {"quota_exhausted": [forever]})
        assert enrich.quota_blocked() == [forever]

    def test_matching_company_returns_its_rule(self, config_dir):
        config_dir(enrich, {"quota_exhausted": [self.RULE]})
        assert enrich.quota_rule_for("TikTok") == self.RULE

    def test_sibling_company_shares_the_cap(self, config_dir):
        # TikTok and ByteDance share one allowance across the whole 2027
        # intern project; matching only the exact name misses the sibling.
        config_dir(enrich, {"quota_exhausted": [self.RULE]})
        assert enrich.quota_rule_for("ByteDance Inc.") == self.RULE

    def test_unrelated_company_is_not_blocked(self, config_dir):
        config_dir(enrich, {"quota_exhausted": [self.RULE]})
        assert enrich.quota_rule_for("Microsoft") is None

    def test_missing_company_name_is_not_blocked(self, config_dir):
        config_dir(enrich, {"quota_exhausted": [self.RULE]})
        assert enrich.quota_rule_for(None) is None
