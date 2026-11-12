"""Conformance tests: spec section 8, one test per numbered point.

These exist so the specification is testable rather than aspirational. If you
implement this format elsewhere, this file describes what a passing
implementation must do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skilllock.hashing import hash_skill
from skilllock.lockfile import (
    FILENAME,
    Dependency,
    FileEntry,
    Lockfile,
    LockfileError,
    SkillEntry,
    read,
    write,
)
from skilllock.verify import verify_skill


def _skill(tmp_path: Path, name: str = "demo") -> Path:
    skill = tmp_path / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_bytes(b"---\nname: demo\n---\n\n# T\n")
    return skill


def _entry(skill: Path, name: str = "demo") -> SkillEntry:
    digest, files = hash_skill(skill)
    return SkillEntry(
        name=name,
        source="path:.",
        revision="local",
        path=str(skill.relative_to(skill.parents[1])),
        hash=digest,
        files=[FileEntry(f.path, f.digest) for f in files],
    )


def test_point_1_rejects_unknown_version(tmp_path: Path):
    path = tmp_path / FILENAME
    path.write_text('version = 2\n\n[[skill]]\nname = "a"\n', encoding="utf-8")
    with pytest.raises(LockfileError, match="unsupported lockfile version 2"):
        read(path)


def test_point_2_rejects_missing_required_field(tmp_path: Path):
    path = tmp_path / FILENAME
    path.write_text(
        'version = 1\n\n[[skill]]\nname = "a"\nsource = "path:."\n'
        'revision = "local"\npath = "p"\n',
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="missing required field `hash`"):
        read(path)


def test_point_3_rejects_branch_revision():
    with pytest.raises(LockfileError, match="not an immutable identifier"):
        from skilllock.lockfile import validate

        validate(
            Lockfile(
                skills=[
                    SkillEntry(
                        name="a",
                        source="github:o/r",
                        revision="develop",
                        path="p",
                        hash="sha256:" + "0" * 64,
                    )
                ]
            )
        )


def test_point_4_verifies_directory_and_file_hashes(tmp_path: Path):
    skill = _skill(tmp_path)
    entry = _entry(skill)
    assert verify_skill(entry, skill).ok

    # Corrupt one byte: both the file hash and the directory hash must notice.
    (skill / "SKILL.md").write_bytes(b"---\nname: demo\n---\n\n# T!\n")
    result = verify_skill(entry, skill)
    assert not result.ok
    assert any("content differs" in p for p in result.problems)
    assert any("directory hash mismatch" in p for p in result.problems)


def test_point_5_fails_on_unlisted_file(tmp_path: Path):
    skill = _skill(tmp_path)
    entry = _entry(skill)
    (skill / "unlocked.md").write_bytes(b"# not reviewed\n")
    result = verify_skill(entry, skill)
    assert not result.ok
    assert any("unlisted file" in p for p in result.problems)


def test_point_6_fails_on_unresolved_dependency(tmp_path: Path):
    path = tmp_path / FILENAME
    lock = Lockfile(
        skills=[
            SkillEntry(
                name="a",
                source="path:.",
                revision="local",
                path="a",
                hash="sha256:" + "0" * 64,
                dependencies=[Dependency("nowhere", "*")],
            )
        ]
    )
    write(lock, path)
    with pytest.raises(LockfileError, match="has no entry in this lockfile"):
        read(path)


def test_point_7_installing_executes_nothing(tmp_path: Path):
    """A locked skill is fetched and verified. No script is ever run.

    This is asserted structurally: the module that verifies a skill imports only
    hashing and lockfile helpers, never subprocess.
    """
    import skilllock.verify as verify_module

    source = Path(verify_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "eval(", "exec("):
        assert forbidden not in source, (
            f"verification must not execute anything, found {forbidden}"
        )


def test_full_conformance_round_trip(tmp_path: Path):
    """A conforming file written by this tool must read back and verify."""
    skill = _skill(tmp_path)
    entry = _entry(skill)
    lock = Lockfile(skills=[entry])
    path = tmp_path / FILENAME
    write(lock, path)

    back = read(path)
    assert verify_skill(back.by_name("demo"), skill).ok