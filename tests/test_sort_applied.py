"""Matching Simplify rows to generated resumes in sort_applied.py."""
import sort_applied


def _row(url, company="Acme"):
    return {"Job URL": url, "Company Name": company}


class TestFind:
    def test_matches_on_the_apply_url(self):
        briefs = {"Acme-Intern-123": sort_applied.norm(
            "https://jobs.lever.co/acme/1111-2222-3333/apply")}
        files = {"Acme-Intern-123": ["x.docx"]}
        stem, how = sort_applied.find(
            _row("https://jobs.lever.co/acme/1111-2222-3333/apply"), briefs, files)
        assert (stem, how) == ("Acme-Intern-123", "url")

    def test_placeholder_url_never_matches(self):
        # Regression: a brief recording "n/a" matched any URL containing the
        # substring, e.g. ".../actian/a28a..." filed the general resume as an
        # application to Actian.
        briefs = {"Resume": "n/a"}
        files = {"Resume": ["Resume.docx"]}
        stem, _ = sort_applied.find(
            _row("https://jobs.lever.co/actian/a28a9ac3-70eb-4c5d/apply", "Zzz"),
            briefs, files)
        assert stem is None

    def test_short_urls_do_not_substring_match(self):
        briefs = {"Tiny": "a.co/x"}
        files = {"Tiny": ["t.docx"]}
        stem, _ = sort_applied.find(
            _row("https://example.com/careers/a.co/x/long-path-here", "Zzz"),
            briefs, files)
        assert stem is None


class TestBriefApplyUrls:
    def test_placeholder_values_become_empty(self, tmp_path, monkeypatch):
        (tmp_path / "briefs").mkdir()
        (tmp_path / "briefs" / "Resume.md").write_text(
            "# Resume\n\n**Apply:** n/a\n", encoding="utf-8")
        (tmp_path / "briefs" / "Real.md").write_text(
            "# Real\n\n**Apply:** https://boards.greenhouse.io/acme/jobs/42\n",
            encoding="utf-8")
        monkeypatch.setattr(sort_applied, "BASE", str(tmp_path))
        urls = sort_applied.brief_apply_urls()
        assert urls["Resume"] == ""
        assert urls["Real"] == "https://boards.greenhouse.io/acme/jobs/42"
