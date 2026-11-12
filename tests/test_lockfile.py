"""Tests for reading, writing and validating the lockfile format."""

from __future__ import annotations

from pathlib import Path

import pytest

from skilllock.lockfile import (
    FILENAME,
    Dependency,
    FileEntry,
    Lockfile,
    LockfileError,
    SkillEntry,
    read,
    render,
    validate,
    write,
)


def _entry(name: str = "demo", **kwargs) -> SkillEntry:
    defaults = dict(
        name=name,
        source="github:owner/repo",
        revision="a" * 40,
        path=f"skills/{name}",
        hash="sha256:" + "b" * 64,
        files=[FileEntry("SKILL.md", "sha256:" + "c" * 64)],
    )
    defaults.update(kwargs)
    return SkillEntry(**defaults)


# --- validate ---------------------------------------------------------------


def test_validate_accepts_well_formed():
    lock = Lockfile(skills=[_entry()])
    validate(lock)


def test_rejects_unsupported_version():
    lock = Lockfile(version=99, skills=[_entry()])
    with pytest.raises(LockfileError, match="unsupported lockfile version 99"):
        validate(lock)


def test_rejects_duplicate_names():
    lock = Lockfile(skills=[_entry("same"), _entry("same")])
    with pytest.raises(LockfileError, match="duplicate skill name"):
        validate(lock)


def test_rejects_branch_name_revision():
    """A branch in a lockfile defeats the point of having one."""
    lock = Lockfile(skills=[_entry(revision="main")])
    with pytest.raises(LockfileError, match="not an immutable identifier"):
        validate(lock)


def test_accepts_version_tag_revision():
    lock = Lockfile(skills=[_entry(revision="v1.2.3")])
    validate(lock)


def test_rejects_missing_dependency_entry():
    lock = Lockfile(
        skills=[_entry("a", dependencies=[Dependency("gone", "*")])]
    )
    with pytest.raises(LockfileError, match="has no entry in this lockfile"):
        validate(lock)


def test_accepts_present_dependency():
    lock = Lockfile(
        skills=[
            _entry("a", dependencies=[Dependency("b", "*")]),
            _entry("b"),
        ]
    )
    validate(lock)


def test_path_source_requires_local_revision():
    lock = Lockfile(skills=[_entry(source="path:./x", revision="v1")])
    with pytest.raises(LockfileError, match='must use revision "local"'):
        validate(lock)


def test_path_source_with_local_revision_ok():
    validate(Lockfile(skills=[_entry(source="path:./x", revision="local")]))


# --- render / read round trip ----------------------------------------------


def test_render_and_read_round_trip(tmp_path: Path):
    lock = Lockfile(skills=[_entry("a"), _entry("b")])
    path = tmp_path / FILENAME
    write(lock, path)
    back = read(path)
    assert back.names() == ["a", "b"]
    assert back.version == 1
    assert back.by_name("a").files[0].path == "SKILL.md"


def test_render_is_deterministic(tmp_path: Path):
    lock = Lockfile(skills=[_entry("b"), _entry("a")])
    first = render(lock)
    second = render(lock)
    assert first == second
    # Sorted by name, so a re-lock produces no diff noise.
    assert first.index('name = "a"') < first.index('name = "b"')


def test_render_includes_spec_reference():
    text = render(Lockfile(skills=[_entry()]))
    assert "spec/lockfile-v1.md" in text
    assert "version = 1" in text


def test_round_trip_preserves_dependencies(tmp_path: Path):
    lock = Lockfile(
        skills=[
            _entry("a", dependencies=[Dependency("b", "^1.0")]),
            _entry("b"),
        ]
    )
    path = tmp_path / FILENAME
    write(lock, path)
    back = read(path)
    assert back.by_name("a").dependencies[0].name == "b"
    assert back.by_name("a").dependencies[0].constraint == "^1.0"


def test_round_trip_preserves_files(tmp_path: Path):
    entry = _entry(
        files=[
            FileEntry("SKILL.md", "sha256:" + "1" * 64),
            FileEntry("references/x.md", "sha256:" + "2" * 64),
        ]
    )
    lock = Lockfile(skills=[entry])
    path = tmp_path / FILENAME
    write(lock, path)
    back = read(path)
    assert [f.path for f in back.by_name("demo").files] == [
        "SKILL.md",
        "references/x.md",
    ]


def test_read_rejects_missing_version(tmp_path: Path):
    path = tmp_path / FILENAME
    path.write_text('[[skill]]\nname = "a"\n', encoding="utf-8")
    with pytest.raises(LockfileError, match="`version` must be an integer"):
        read(path)


def test_read_rejects_missing_field(tmp_path: Path):
    path = tmp_path / FILENAME
    path.write_text(
        'version = 1\n\n[[skill]]\nname = "a"\nsource = "github:o/r"\n'
        'revision = "v1"\npath = "p"\n',
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="missing required field `hash`"):
        read(path)


def test_read_rejects_invalid_toml(tmp_path: Path):
    path = tmp_path / FILENAME
    path.write_text("version = [unclosed\n", encoding="utf-8")
    with pytest.raises(LockfileError, match="not valid TOML"):
        read(path)


def test_written_file_uses_lf(tmp_path: Path):
    """CRLF in a lockfile would make it differ per platform for no reason."""
    path = tmp_path / FILENAME
    write(Lockfile(skills=[_entry()]), path)
    assert b"\r\n" not in path.read_bytes()