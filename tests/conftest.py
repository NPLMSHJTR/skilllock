"""Shared fixtures for skilllock tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def make_skill(root: Path, name: str, body: str = "# Title\n\nDo it.\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing.\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with two skills and one dependency between them."""
    review = make_skill(tmp_path / "skills", "review")
    (review / "references").mkdir()
    (review / "references" / "severity.md").write_text("# Severity\n", encoding="utf-8")

    changelog = make_skill(tmp_path / "skills", "changelog")
    (changelog / "SKILL.md").write_text(
        "---\n"
        "name: changelog\n"
        "description: Use when writing release notes.\n"
        "metadata:\n"
        "  version: \"1.2.0\"\n"
        "---\n\n# Changelog\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# empty\n", encoding="utf-8")
    return tmp_path