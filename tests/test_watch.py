"""Filtering and scoring in watch.py.

These are the functions that decide whether a posting is ever seen at all. A
false negative here is silent: the posting is dropped and nothing reports it.
"""
import time

import watch


# ------------------------------------------------------------- matches_location
class TestMatchesLocation:
    def test_empty_filter_accepts_everything(self):
        assert watch.matches_location({"locations": ["Berlin"]}, []) is True

    def test_posting_with_no_location_is_kept(self):
        # Unspecified location is common on remote reqs; dropping them loses
        # real postings, so the filter deliberately lets them through.
        assert watch.matches_location({"locations": []}, [", ca"]) is True
        assert watch.matches_location({}, [", ca"]) is True

    def test_plain_substring_match(self):
        assert watch.matches_location({"locations": ["Remote"]}, ["remote"]) is True

    def test_match_is_case_insensitive_on_both_sides(self):
        assert watch.matches_location({"locations": ["REMOTE"]}, ["Remote"]) is True

    def test_state_code_matches_at_end_of_string(self):
        assert watch.matches_location({"locations": ["Norco, CA"]}, [", ca"]) is True

    def test_state_code_matches_before_a_comma(self):
        assert watch.matches_location(
            {"locations": ["Redmond, WA, USA"]}, [", wa"]) is True

    def test_state_code_does_not_match_inside_a_longer_word(self):
        # The whole reason the state-code branch exists: a naive substring
        # check on ", ca" pulls in every Canadian posting.
        assert watch.matches_location(
            {"locations": ["Toronto, Canada"]}, [", ca"]) is False

    def test_any_location_matching_is_enough(self):
        assert watch.matches_location(
            {"locations": ["Berlin", "Norco, CA"]}, [", ca"]) is True

    def test_no_match_is_rejected(self):
        assert watch.matches_location({"locations": ["Berlin"]}, [", ca"]) is False


# ---------------------------------------------------------------- matches_title
class TestMatchesTitle:
    def test_keyword_present(self):
        assert watch.matches_title("Software Engineer Intern", ["software"]) is True

    def test_title_case_is_ignored(self):
        assert watch.matches_title("SOFTWARE ENGINEER", ["software"]) is True

    def test_no_keyword_present(self):
        assert watch.matches_title("Marketing Intern", ["software", "swe"]) is False

    def test_empty_keyword_list_matches_nothing(self):
        assert watch.matches_title("Software Engineer", []) is False


# ---------------------------------------------------------------- matches_terms
class TestMatchesTerms:
    def test_empty_terms_are_kept(self):
        assert watch.matches_terms([], ["Summer 2027"]) is True

    def test_allowed_term(self):
        assert watch.matches_terms(["Summer 2027"], ["Summer 2027"]) is True

    def test_na_is_always_allowed(self):
        # Most Summer 2027 reqs carry "N/A" rather than a real term; filtering
        # strictly on the term string drops the majority of live postings.
        assert watch.matches_terms(["N/A"], ["Summer 2027"]) is True

    def test_disallowed_term(self):
        assert watch.matches_terms(["Fall 2026"], ["Summer 2027"]) is False


# ---------------------------------------------------------------- score_posting
class TestScorePosting:
    def _posting(self, **kw):
        # Old date by default so the recency bonus doesn't leak into tests
        # that aren't about recency.
        base = {"title": "", "company_name": "", "date_posted": time.time() - 30 * 86400}
        base.update(kw)
        return base

    def test_empty_posting_scores_zero(self):
        assert watch.score_posting(self._posting()) == 0

    def test_software_engineer_title(self):
        assert watch.score_posting(self._posting(title="Software Engineer Intern")) == 5

    def test_swe_abbreviation_counts(self):
        assert watch.score_posting(self._posting(title="SWE Intern")) == 5

    def test_backend_bonus_stacks_with_swe(self):
        assert watch.score_posting(
            self._posting(title="Backend Software Engineer")) == 8

    def test_clearance_bonus(self):
        assert watch.score_posting(self._posting(title="Security Engineer")) == 4

    def test_defense_contractor_bonus(self):
        assert watch.score_posting(self._posting(company_name="RTX")) == 6

    def test_defense_bonus_matches_within_a_longer_name(self):
        assert watch.score_posting(
            self._posting(company_name="Lockheed Martin Space")) == 6

    def test_no_sponsorship_penalty(self):
        assert watch.score_posting(
            self._posting(sponsorship="Sponsorship Not Offered")) == -1

    def test_recent_posting_bonus(self):
        assert watch.score_posting(
            self._posting(date_posted=time.time() - 3600)) == 2

    def test_posting_three_days_old_gets_no_recency_bonus(self):
        assert watch.score_posting(
            self._posting(date_posted=time.time() - 4 * 86400)) == 0

    def test_bonuses_combine(self):
        # SWE (5) + platform (3) + defense (6) + fresh (2)
        assert watch.score_posting(self._posting(
            title="Software Engineer, Platform",
            company_name="Leidos",
            date_posted=time.time(),
        )) == 16


# --------------------------------------------------------------- seen-set round trip
class TestSeenRoundTrip:
    def test_save_then_load_preserves_ids(self, tmp_path, monkeypatch):
        path = tmp_path / "seen.json"
        monkeypatch.setattr(watch, "SEEN_PATH", str(path))
        watch.save_seen({"b", "a", "c"})
        assert watch.load_seen() == {"a", "b", "c"}

    def test_load_without_a_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "SEEN_PATH", str(tmp_path / "missing.json"))
        assert watch.load_seen() == set()
