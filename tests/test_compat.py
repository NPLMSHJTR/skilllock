"""Tests that lock the Python 3.9 compatibility path.

The first CI run failed on every 3.9 job with:

    TypeError: write_text() got an unexpected keyword argument 'newline'

That argument exists only from 3.10, and developing on 3.13 hides it. These tests
cover the two places compatibility is at risk: file writing, and the absence of
`tomllib`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from skilllock import lockfile as lf
from skilllock.lockfile import FILENAME, FileEntry, Lockfile, SkillEntry, read, write


@pytest.fixture
def sample_lock() -> Lockfile:
    return Lockfile(
        skills=[
            SkillEntry(
                name="demo",
                source="path:.",
                revision="local",
                path="skills/demo",
                hash="sha256:" + "a" * 64,
                files=[FileEntry("SKILL.md", "sha256:" + "b" * 64)],
            )
        ]
    )


def test_write_works_without_newline_kwarg_on_path_write_text(tmp_path: Path, sample_lock):
    """`Path.write_text(newline=)` is 3.10+. This must not be used."""
    path = tmp_path / FILENAME
    write(sample_lock, path)
    assert path.exists()


def test_written_file_has_lf_only(tmp_path: Path, sample_lock):
    path = tmp_path / FILENAME
    write(sample_lock, path)
    raw = path.read_bytes()
    assert b"\r\n" not in raw, "lockfile must use LF on every platform"
    assert b"\n" in raw


def test_fallback_parser_reads_a_real_lockfile(tmp_path: Path, sample_lock, monkeypatch):
    """Simulates 3.9/3.10, where tomllib does not exist."""
    path = tmp_path / FILENAME
    write(sample_lock, path)

    monkeypatch.setattr(lf, "_tomllib", None)
    back = read(path)

    assert back.names() == ["demo"]
    assert back.by_name("demo").files[0].path == "SKILL.md"
    assert back.version == 1


def test_fallback_parser_reads_dependencies(tmp_path: Path, monkeypatch):
    path = tmp_path / FILENAME
    path.write_text(
        'version = 1\n\n[[skill]]\nname = "a"\nsource = "path:."\n'
        'revision = "local"\npath = "a"\nhash = "sha256:aa"\n\n'
        '  [[skill.dependency]]\n  name = "b"\n  constraint = "^1.0"\n\n'
        '[[skill]]\nname = "b"\nsource = "path:."\nrevision = "local"\n'
        'path = "b"\nhash = "sha256:bb"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(lf, "_tomllib", None)
    lock = read(path)
    assert lock.by_name("a").dependencies[0].constraint == "^1.0"


def test_no_310_only_apis_in_source():
    """A structural guard: these APIs do not exist on 3.9."""
    source_root = Path(__file__).resolve().parents[1] / "src"
    forbidden = (
        "write_text(encoding=\"utf-8\", newline=",
        "read_text(encoding=\"utf-8\", newline=",
        "zip(..., strict=",
        "itertools.pairwise",
        "dataclass(slots=True",
        "dataclass(kw_only=True",
    )
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                offenders.append(f"{path.name}: {pattern}")
    assert not offenders, f"3.10+ only API used: {offenders}"


def test_tomllib_import_is_optional():
    """The module must import on a Python without tomllib."""
    assert hasattr(lf, "_tomllib") or sys.version_info < (3, 11)
    # The fallback must exist regardless.
    assert callable(lf._parse_fallback)