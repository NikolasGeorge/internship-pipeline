"""Tab-opening guards in open_apps.py.

The quota check is duplicated across enrich.py, tailor.py, and open_apps.py --
each reads the same config but keys off a different thing (company name,
brief filename, company name again). Testing all three is the only way a
change to the rule format fails loudly instead of in one place only.
"""
import open_apps


class TestLoad:
    def test_reads_json(self, tmp_path):
        path = tmp_path / "x.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert open_apps.load(str(path), {}) == {"a": 1}

    def test_missing_file_returns_the_default(self, tmp_path):
        assert open_apps.load(str(tmp_path / "nope.json"), {"fallback": True}) == {
            "fallback": True}

    def test_malformed_json_returns_the_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert open_apps.load(str(path), []) == []


class TestQuotaBlockedCompany:
    RULE = {"match": ["tiktok", "bytedance"], "until": "2999-12-31"}

    def test_a_capped_company_is_blocked(self, config_dir):
        config_dir(open_apps, {"quota_exhausted": [self.RULE]})
        assert open_apps.quota_blocked_company("TikTok") is True

    def test_the_sibling_company_is_blocked_too(self, config_dir):
        config_dir(open_apps, {"quota_exhausted": [self.RULE]})
        assert open_apps.quota_blocked_company("ByteDance Ltd") is True

    def test_an_uncapped_company_opens_normally(self, config_dir):
        config_dir(open_apps, {"quota_exhausted": [self.RULE]})
        assert open_apps.quota_blocked_company("Microsoft") is False

    def test_an_expired_cap_stops_blocking(self, config_dir):
        config_dir(open_apps, {"quota_exhausted": [dict(self.RULE, until="2000-01-01")]})
        assert open_apps.quota_blocked_company("TikTok") is False

    def test_a_missing_config_blocks_nothing(self, config_dir):
        config_dir(open_apps, {})
        assert open_apps.quota_blocked_company("TikTok") is False

    def test_a_missing_company_name_is_not_blocked(self, config_dir):
        config_dir(open_apps, {"quota_exhausted": [self.RULE]})
        assert open_apps.quota_blocked_company(None) is False


class TestResumePrefix:
    def test_name_becomes_a_filename_safe_prefix(self, tmp_path, monkeypatch):
        path = tmp_path / "resume_data.json"
        path.write_text('{"name": "Test Candidate"}', encoding="utf-8")
        monkeypatch.setattr(open_apps, "RESUME_DATA", str(path))
        assert open_apps.resume_prefix() == "Test_Candidate"

    def test_a_missing_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(open_apps, "RESUME_DATA", str(tmp_path / "missing.json"))
        assert open_apps.resume_prefix() == "Resume"
