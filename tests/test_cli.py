"""Tests for the CLI: lock, verify, check, show."""

from __future__ import annotations

import json
from pathlib import Path

from skilllock.cli import main
from skilllock.lockfile import FILENAME, read


def test_lock_writes_file(project: Path, capsys):
    assert main(["lock", str(project)]) == 0
    assert (project / FILENAME).exists()
    out = capsys.readouterr().out
    assert "2 skill(s)" in out


def test_lock_records_both_skills(project: Path):
    main(["lock", str(project)])
    lock = read(project / FILENAME)
    assert sorted(lock.names()) == ["changelog", "review"]


def test_lock_records_nested_files(project: Path):
    main(["lock", str(project)])
    lock = read(project / FILENAME)
    review = lock.by_name("review")
    paths = [f.path for f in review.files]
    assert "SKILL.md" in paths
    assert "references/severity.md" in paths


def test_lock_no_skills_exits_two(empty_project: Path, capsys):
    assert main(["lock", str(empty_project)]) == 2
    assert "no skills found" in capsys.readouterr().err


def test_verify_passes_after_lock(project: Path, capsys):
    main(["lock", str(project)])
    capsys.readouterr()
    assert main(["verify", str(project), "--no-color"]) == 0
    assert "verified" in capsys.readouterr().out


def test_verify_catches_tampering(project: Path, capsys):
    main(["lock", str(project)])
    (project / "skills" / "review" / "SKILL.md").write_text(
        "---\nname: review\n---\n\n# changed\n", encoding="utf-8"
    )
    capsys.readouterr()
    assert main(["verify", str(project), "--no-color"]) == 1
    assert "content differs" in capsys.readouterr().out


def test_verify_catches_unlisted_file(project: Path, capsys):
    main(["lock", str(project)])
    (project / "skills" / "review" / "extra.md").write_text("x\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["verify", str(project), "--no-color"]) == 1
    assert "unlisted file" in capsys.readouterr().out


def test_verify_missing_lockfile_exits_two(empty_project: Path, capsys):
    assert main(["verify", str(empty_project)]) == 2
    assert "no skilllock.toml" in capsys.readouterr().err


def test_verify_json_shape(project: Path, capsys):
    main(["lock", str(project)])
    capsys.readouterr()  # discard the lock output before capturing JSON
    main(["verify", str(project), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"lockfile", "ok", "skills"}
    assert payload["ok"] is True
    assert set(payload["skills"][0]) == {"name", "ok", "checked", "problems"}


def test_check_reports_integrity_and_deps(project: Path, capsys):
    main(["lock", str(project)])
    capsys.readouterr()
    assert main(["check", str(project), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"ok", "integrity", "dependency_problems"}
    assert payload["ok"] is True


def test_check_catches_dependency_violation(project: Path, capsys):
    """A skill requiring a version the resolved set does not provide."""
    changelog = project / "skills" / "changelog" / "SKILL.md"
    changelog.write_text(
        "---\nname: changelog\ndescription: d\nmetadata:\n  version: \"2.0.0\"\n"
        "dependencies:\n  - review@^3.0\n---\n\n# C\n",
        encoding="utf-8",
    )
    main(["lock", str(project)])
    capsys.readouterr()
    assert main(["check", str(project)]) == 1
    assert "does not satisfy" in capsys.readouterr().out


def test_check_accepts_satisfied_dependency(project: Path, capsys):
    changelog = project / "skills" / "changelog" / "SKILL.md"
    changelog.write_text(
        "---\nname: changelog\ndescription: d\nmetadata:\n  version: \"1.2.0\"\n"
        "dependencies:\n  - review@*\n---\n\n# C\n",
        encoding="utf-8",
    )
    main(["lock", str(project)])
    capsys.readouterr()
    assert main(["check", str(project)]) == 0


def test_show_lists_skills(project: Path, capsys):
    main(["lock", str(project)])
    capsys.readouterr()
    assert main(["show", str(project)]) == 0
    out = capsys.readouterr().out
    assert "review" in out
    assert "revision" in out


def test_show_missing_lockfile_exits_two(empty_project: Path, capsys):
    assert main(["show", str(empty_project)]) == 2


def test_lock_is_reproducible(project: Path):
    """Locking twice with no changes must produce identical files."""
    main(["lock", str(project)])
    first = (project / FILENAME).read_bytes()
    main(["lock", str(project)])
    assert (project / FILENAME).read_bytes() == first


def test_lock_rejects_branch_revision(project: Path, capsys):
    assert main(["lock", str(project), "--source", "github:o/r", "--revision", "main"]) == 1
    assert "not an immutable identifier" in capsys.readouterr().err


def test_lock_accepts_commit_sha(project: Path, capsys):
    sha = "a" * 40
    assert main(["lock", str(project), "--source", "github:o/r", "--revision", sha]) == 0
    lock = read(project / FILENAME)
    assert lock.by_name("review").revision == sha