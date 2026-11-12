"""Tests for verification (spec section 8, points 4 and 5).

The critical behaviour: an unlisted file on disk must fail verification. A file
nobody locked is a file nobody reviewed, and it will still be read by an agent.
"""

from __future__ import annotations

from pathlib import Path

from skilllock.hashing import hash_skill
from skilllock.lockfile import FileEntry, SkillEntry
from skilllock.verify import verify_all, verify_skill


def _entry_for(skill_dir: Path, name: str = "demo") -> SkillEntry:
    digest, files = hash_skill(skill_dir)
    return SkillEntry(
        name=name,
        source="path:.",
        revision="local",
        path=str(skill_dir.name),
        hash=digest,
        files=[FileEntry(path=f.path, hash=f.digest) for f in files],
    )


def _make(tmp_path: Path, name: str = "demo") -> Path:
    skill = tmp_path / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_bytes(b"---\nname: demo\n---\n\n# Title\n")
    return skill


def test_unchanged_skill_verifies(tmp_path: Path):
    skill = _make(tmp_path)
    result = verify_skill(_entry_for(skill), skill)
    assert result.ok, result.problems
    assert result.checked == 1


def test_changed_content_fails(tmp_path: Path):
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    (skill / "SKILL.md").write_bytes(b"---\nname: demo\n---\n\n# Changed\n")
    result = verify_skill(entry, skill)
    assert not result.ok
    assert any("content differs: SKILL.md" in p for p in result.problems)


def test_unlisted_file_fails(tmp_path: Path):
    """Spec point 5."""
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    (skill / "sneaked-in.md").write_bytes(b"do something else\n")
    result = verify_skill(entry, skill)
    assert not result.ok
    assert any("unlisted file present on disk: sneaked-in.md" in p for p in result.problems)


def test_missing_file_fails(tmp_path: Path):
    skill = _make(tmp_path)
    (skill / "extra.md").write_bytes(b"x\n")
    entry = _entry_for(skill)
    (skill / "extra.md").unlink()
    result = verify_skill(entry, skill)
    assert not result.ok
    assert any("locked file is missing on disk: extra.md" in p for p in result.problems)


def test_directory_hash_mismatch_reported(tmp_path: Path):
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    # Change the recorded hash but keep the file list valid.
    broken = SkillEntry(
        name=entry.name,
        source=entry.source,
        revision=entry.revision,
        path=entry.path,
        hash="sha256:" + "0" * 64,
        files=entry.files,
    )
    result = verify_skill(broken, skill)
    assert not result.ok
    assert any("directory hash mismatch" in p for p in result.problems)


def test_missing_directory_fails(tmp_path: Path):
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    result = verify_skill(entry, tmp_path / "gone")
    assert not result.ok
    assert any("directory does not exist" in p for p in result.problems)


def test_nested_files_verified(tmp_path: Path):
    skill = _make(tmp_path)
    refs = skill / "references"
    refs.mkdir()
    (refs / "a.md").write_bytes(b"# A\n")
    entry = _entry_for(skill)
    assert verify_skill(entry, skill).ok

    (refs / "a.md").write_bytes(b"# A changed\n")
    result = verify_skill(entry, skill)
    assert any("content differs: references/a.md" in p for p in result.problems)


def test_excluded_files_do_not_cause_failure(tmp_path: Path):
    """A .DS_Store appearing is not tampering."""
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    (skill / ".DS_Store").write_bytes(b"junk")
    result = verify_skill(entry, skill)
    assert result.ok, result.problems


def test_verify_all_reports_missing_directory(tmp_path: Path):
    skill = _make(tmp_path)
    entry = _entry_for(skill)
    results = verify_all({}, [entry])
    assert not results[0].ok
    assert any("no directory provided" in p for p in results[0].problems)


def test_verify_all_multiple(tmp_path: Path):
    a = _make(tmp_path, "a")
    b = _make(tmp_path, "b")
    entries = [_entry_for(a, "a"), _entry_for(b, "b")]
    results = verify_all({"a": a, "b": b}, entries)
    assert all(r.ok for r in results)