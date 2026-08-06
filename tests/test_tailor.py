"""Selection and ordering in tailor.py.

Tailoring is allowed to reorder and drop. It is never allowed to invent. The
last class here is the one that matters most: every string the generated .docx
contains has to come from resume_data.json verbatim.
"""
import pytest

tailor = pytest.importorskip(
    "tailor", reason="tailor.py requires python-docx")


BRIEF = """# Acme Corp — Software Engineer Intern

**Verdict:** APPLY

**Score:** 14

## Full description

We want someone who knows Python and distributed systems.
"""


@pytest.fixture
def brief(tmp_path):
    def _write(name="Acme-Software-Engineer-01863012.md", text=BRIEF):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)
    return _write


# ------------------------------------------------------------- desc_from_brief
class TestDescFromBrief:
    def test_only_the_description_section_is_returned(self, brief):
        desc = tailor.desc_from_brief(brief())
        assert "python and distributed systems" in desc
        assert "verdict" not in desc

    def test_result_is_lowercased_for_matching(self, brief):
        assert tailor.desc_from_brief(brief()) == tailor.desc_from_brief(brief()).lower()

    def test_brief_without_the_section_falls_back_to_the_whole_file(self, brief):
        desc = tailor.desc_from_brief(brief(text="# Acme\n\nNo section header here."))
        assert "no section header here" in desc


# ---------------------------------------------------------- verdict_from_brief
class TestVerdictFromBrief:
    @pytest.mark.parametrize("verdict", ["APPLY", "REVIEW", "SKIP"])
    def test_each_verdict_is_read_back(self, brief, verdict):
        path = brief(text=BRIEF.replace("APPLY", verdict))
        assert tailor.verdict_from_brief(path) == verdict

    def test_a_brief_without_a_verdict_is_unknown(self, brief):
        assert tailor.verdict_from_brief(brief(text="# Acme\n")) == "UNKNOWN"


# ---------------------------------------------------------------- company_title
class TestCompanyTitle:
    def test_company_and_title_are_split_on_the_em_dash(self, brief):
        assert tailor.company_title(brief()) == ("Acme Corp", "Software Engineer Intern")

    def test_a_heading_without_a_dash_yields_an_empty_title(self, brief):
        assert tailor.company_title(brief(text="# Acme Corp\n")) == ("Acme Corp", "")


# ------------------------------------------------------------------- relevance
class TestRelevance:
    def test_no_tags_scores_zero(self):
        assert tailor.relevance([], "python backend role") == 0

    def test_a_missing_tag_scores_zero(self):
        assert tailor.relevance(["rust"], "python backend role") == 0

    def test_a_long_tag_is_worth_more_than_a_short_one(self):
        # Short tokens match by accident far more often, so they are worth
        # less; "api" appearing inside prose should not outrank "kubernetes".
        assert tailor.relevance(["kubernetes"], "kubernetes") == 3
        assert tailor.relevance(["api"], "api") == 2

    def test_tag_case_is_ignored(self):
        assert tailor.relevance(["Python"], "python role") == 3

    def test_scores_accumulate_across_tags(self):
        assert tailor.relevance(["python", "docker"], "python and docker") == 6

    def test_stopwords_never_contribute(self):
        # Without the stopword filter every project scores on "team" and
        # "experience", and the ordering stops meaning anything.
        assert tailor.relevance(["team", "experience", "required"], BRIEF.lower()) == 0


# --------------------------------------------------------------- order_projects
class TestOrderProjects:
    def test_the_better_match_is_promoted(self, resume_data):
        ordered, _ = tailor.order_projects(resume_data, "we use python and automation")
        assert ordered[0]["name"] == "Secondproject"

    def test_bullet_tags_count_toward_the_project_score(self, resume_data):
        # Tags live on bullets as well as projects; ignoring them loses most
        # of the signal, since bullets carry the specific technology names.
        ordered, _ = tailor.order_projects(resume_data, "experience with workday")
        assert ordered[0]["name"] == "Secondproject"

    def test_ties_keep_the_original_order(self, resume_data):
        ordered, _ = tailor.order_projects(resume_data, "nothing matches here")
        assert [p["name"] for p in ordered] == ["Firstproject", "Secondproject"]

    def test_ordering_is_deterministic(self, resume_data):
        first, _ = tailor.order_projects(resume_data, "python unity")
        second, _ = tailor.order_projects(resume_data, "python unity")
        assert [p["name"] for p in first] == [p["name"] for p in second]

    def test_every_project_survives_the_reordering(self, resume_data):
        ordered, _ = tailor.order_projects(resume_data, "python")
        assert len(ordered) == len(resume_data["projects"])

    def test_scores_are_reported_per_project(self, resume_data):
        ordered, scores = tailor.order_projects(resume_data, "python automation")
        assert scores[id(ordered[0])] > scores[id(ordered[-1])]


# ----------------------------------------------------------------- order_skills
class TestOrderSkills:
    def test_named_skills_move_to_the_front(self, resume_data):
        out = tailor.order_skills(resume_data, "strong java background")
        assert out["languages"][0] == "Java"

    def test_slashed_skills_match_on_their_first_half(self, resume_data):
        # "C/C++" never appears verbatim in a posting; matching on "c" alone
        # is what actually surfaces it.
        out = tailor.order_skills(resume_data, "c programming")
        assert out["languages"][0] == "C/C++"

    def test_unmatched_groups_keep_their_original_order(self, resume_data):
        out = tailor.order_skills(resume_data, "nothing relevant")
        assert out["languages"] == ["Python", "Java", "C/C++"]

    def test_no_skill_is_lost_or_duplicated(self, resume_data):
        out = tailor.order_skills(resume_data, "java git")
        for group, items in resume_data["skills"].items():
            assert sorted(out[group]) == sorted(items)

    def test_every_group_is_preserved(self, resume_data):
        out = tailor.order_skills(resume_data, "java")
        assert set(out) == set(resume_data["skills"])


# ------------------------------------------------------------ quota enforcement
class TestQuotaBlockedBrief:
    RULE = {"match": ["tiktok", "bytedance"], "until": "2999-12-31"}

    def test_a_capped_company_is_blocked(self, brief, config_dir, monkeypatch):
        config_dir(tailor, {"quota_exhausted": [self.RULE]})
        assert tailor.quota_blocked_brief(brief("TikTok-Software-Engineer-1.md")) is True

    def test_the_sibling_company_is_blocked_too(self, brief, config_dir):
        config_dir(tailor, {"quota_exhausted": [self.RULE]})
        assert tailor.quota_blocked_brief(brief("ByteDance-SWE-2.md")) is True

    def test_an_uncapped_company_is_not_blocked(self, brief, config_dir):
        config_dir(tailor, {"quota_exhausted": [self.RULE]})
        assert tailor.quota_blocked_brief(brief("Microsoft-SWE-3.md")) is False

    def test_an_expired_cap_stops_blocking(self, brief, config_dir):
        config_dir(tailor, {"quota_exhausted": [dict(self.RULE, until="2000-01-01")]})
        assert tailor.quota_blocked_brief(brief("TikTok-SWE-1.md")) is False

    def test_a_missing_config_blocks_nothing(self, brief, config_dir):
        config_dir(tailor, {})
        assert tailor.quota_blocked_brief(brief("TikTok-SWE-1.md")) is False


# -------------------------------------------------------------- resume_prefix
class TestResumePrefix:
    def test_the_name_becomes_a_filename_safe_prefix(self, tmp_path, monkeypatch):
        path = tmp_path / "resume_data.json"
        path.write_text('{"name": "Test Candidate"}', encoding="utf-8")
        monkeypatch.setattr(tailor, "DATA_PATH", str(path))
        assert tailor.resume_prefix() == "Test_Candidate"

    def test_punctuation_is_collapsed(self, tmp_path, monkeypatch):
        path = tmp_path / "resume_data.json"
        path.write_text('{"name": "A. B. O\'Brien-Smith"}', encoding="utf-8")
        monkeypatch.setattr(tailor, "DATA_PATH", str(path))
        assert tailor.resume_prefix() == "A_B_O_Brien-Smith".replace("-", "_")

    def test_a_missing_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tailor, "DATA_PATH", str(tmp_path / "missing.json"))
        assert tailor.resume_prefix() == "Resume"


# ------------------------------------------------- the guarantee: no invention
class TestGeneratedResumeInventsNothing:
    """Every string in the .docx has to trace back to resume_data.json.

    This is the one property the whole tool rests on. Reordering is fine;
    a word appearing in the output that is not in the source data is not.
    """

    # Section headings and field labels that build_docx emits itself. Anything
    # outside this set has to come from the data.
    TEMPLATE_WORDS = {
        "education", "experience", "projects", "skills", "relevant",
        "coursework", "progress", "honors", "technical", "familiar",
        "affiliations",
    }

    def _text(self, path):
        from docx import Document
        return "\n".join(p.text for p in Document(str(path)).paragraphs)

    def _build(self, tmp_path, data, **kw):
        out = tmp_path / "out.docx"
        tailor.build_docx(data, data["projects"], data["skills"], str(out), **kw)
        return out

    def test_docx_is_written(self, tmp_path, resume_data):
        out = self._build(tmp_path, resume_data)
        assert out.exists() and out.stat().st_size > 0

    def test_the_candidate_name_and_projects_reach_the_page(self, tmp_path, resume_data):
        text = self._text(self._build(tmp_path, resume_data))
        assert "Test Candidate" in text
        assert "Firstproject" in text
        assert "Secondproject" in text

    def test_no_word_appears_that_is_not_in_the_source_data(self, tmp_path, resume_data):
        import json
        source = json.dumps(resume_data).lower()
        for para in self._text(self._build(tmp_path, resume_data)).split("\n"):
            for word in para.split():
                cleaned = word.strip(",.;:()|•—-").lower()
                if len(cleaned) > 3 and cleaned.isalpha():
                    assert cleaned in source or cleaned in self.TEMPLATE_WORDS, (
                        f"{cleaned!r} appears in the resume but not in resume_data.json")

    def test_max_projects_truncates_rather_than_substitutes(self, tmp_path, resume_data):
        text = self._text(self._build(tmp_path, resume_data, max_projects=1))
        assert "Firstproject" in text
        assert "Secondproject" not in text
