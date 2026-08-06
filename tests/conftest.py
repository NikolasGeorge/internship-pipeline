"""Shared fixtures.

The pipeline modules live at the repo root, not in a package, so the root has
to be importable before any `import watch` in a test file resolves.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point a module's BASE_DIR at a throwaway directory holding a config.json.

    quota_blocked() and quota_blocked_brief() read config.json off BASE_DIR at
    call time, so a test that wants a specific quota rule has to relocate
    BASE_DIR rather than edit the real config.
    """
    def _apply(module, config):
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(module, "BASE_DIR", str(tmp_path))
        return tmp_path

    return _apply


@pytest.fixture
def resume_data():
    """A complete resume_data.json in miniature.

    Every key build_docx reads is present, and the two projects carry
    deliberately disjoint tags so ordering assertions have an unambiguous
    winner. Content is invented placeholder text, not anyone's real resume.
    """
    return {
        "name": "Test Candidate",
        "contact": {
            "location": "Somewhere",
            "email": "candidate@example.com",
        },
        "education": [
            {
                "school": "Example University",
                "location": "Somewhere",
                "degree": "Bachelor of Computing",
                "gpa": "4.00",
                "date": "May 2030",
                "coursework": "Algorithms, Databases",
            }
        ],
        "experience": [
            {
                "org": "Example Employer",
                "location": "Somewhere",
                "role": "Intern",
                "date": "Summer 2029",
                "bullets": [{"text": "Wrote software.", "tags": ["python"]}],
            }
        ],
        "projects": [
            {
                "name": "Firstproject",
                "location": "Somewhere",
                "role": "Solo developer",
                "date": "2029",
                "tags": ["unity", "multiplayer"],
                "bullets": [{"text": "Built a thing.", "tags": ["netcode"]}],
            },
            {
                "name": "Secondproject",
                "location": "Somewhere",
                "role": "Solo developer",
                "date": "2030",
                "tags": ["python", "automation"],
                "bullets": [{"text": "Built another thing.", "tags": ["workday"]}],
            },
        ],
        "skills": {
            "languages": ["Python", "Java", "C/C++"],
            "familiar": ["Rust"],
            "tools": ["Git", "Unity"],
            "concepts": ["REST APIs"],
        },
        "affiliations": [{"name": "Example Society"}],
    }
