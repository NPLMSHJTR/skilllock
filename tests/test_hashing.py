"""Tests for hashing, which must match the specification exactly.

Section 5.4 defines the directory hash as a sha256sum-shaped manifest. These tests
pin that construction, because changing it silently invalidates every existing
lockfile.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from skilllock.hashing import (
    FileHash,
    collect_files,
    directory_hash,
    hash_file,
    hash_skill,
    is_excluded,
    normalise_hash,
)


def test_exclusion_rules():
    assert is_excluded(Path(".git/config"))
    assert is_excluded(Path("__pycache__/x.pyc"))
    assert is_excluded(Path("x.pyc"))
    assert is_excluded(Path(".DS_Store"))
    assert is_excluded(Path("Thumbs.db"))
    assert is_excluded(Path("dir/.hidden/file.md"))
    # SKILL.md is never excluded even though the rule excludes dotfiles.
    assert not is_excluded(Path("SKILL.md"))


def test_skill_md_kept_ordinary_files_kept():
    assert not is_excluded(Path("SKILL.md"))
    assert not is_excluded(Path("references/guide.md"))
    assert not is_excluded(Path("scripts/run.py"))


def test_hash_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello\n")
    expected = "sha256:" + hashlib.sha256(b"hello\n").hexdigest()
    assert hash_file(path) == expected


def test_line_endings_are_part_of_the_hash(tmp_path: Path):
    """LF and CRLF hashes differ. This is deliberate and documented in the spec.

    A lockfile records bytes. Normalising line endings would make the hash
    reproducible across platforms but would stop it from detecting a file that
    was converted in transit, so the spec keeps bytes and tells Windows users to
    normalise via .gitattributes.
    """
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"line\n")
    crlf.write_bytes(b"line\r\n")
    assert hash_file(lf) != hash_file(crlf)


def test_normalise_hash_accepts_bare_hex():
    assert normalise_hash("abc123") == "sha256:abc123"
    assert normalise_hash("sha256:abc123") == "sha256:abc123"
    assert normalise_hash("SHA256:ABC123") == "sha256:abc123"


def test_collect_files_sorted_by_path(tmp_path: Path):
    for name in ("b.md", "a.md", "SKILL.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    entries = collect_files(tmp_path)
    assert [e.path for e in entries] == ["SKILL.md", "a.md", "b.md"]


def test_collect_files_skips_excluded(tmp_path: Path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / "a.pyc").write_text("x", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("x", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "y.py").write_text("x", encoding="utf-8")
    assert [e.path for e in collect_files(tmp_path)] == ["SKILL.md"]


def test_directory_hash_is_sha256sum_shaped(tmp_path: Path):
    """Section 5.4: the hash must equal hashing the manifest text."""
    (tmp_path / "SKILL.md").write_bytes(b"# A\n")
    (tmp_path / "b.md").write_bytes(b"# B\n")

    entries = collect_files(tmp_path)
    manifest_lines = []
    for entry in sorted(entries, key=lambda e: e.path.encode()):
        digest_hex = entry.digest.split(":", 1)[1]
        manifest_lines.append(f"{digest_hex}  {entry.path}\n")
    expected = "sha256:" + hashlib.sha256("".join(manifest_lines).encode()).hexdigest()

    assert directory_hash(entries) == expected


def test_directory_hash_independent_of_creation_order(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for directory, order in ((a, ["x.md", "y.md"]), (b, ["y.md", "x.md"])):
        directory.mkdir()
        for name in order:
            (directory / name).write_text(name, encoding="utf-8")
    assert hash_skill(a)[0] == hash_skill(b)[0]


def test_directory_hash_changes_with_content(tmp_path: Path):
    (tmp_path / "SKILL.md").write_text("one\n", encoding="utf-8")
    first = hash_skill(tmp_path)[0]
    (tmp_path / "SKILL.md").write_text("two\n", encoding="utf-8")
    assert hash_skill(tmp_path)[0] != first


def test_directory_hash_changes_with_filename(tmp_path: Path):
    (tmp_path / "a.md").write_text("same\n", encoding="utf-8")
    first = hash_skill(tmp_path)[0]
    (tmp_path / "a.md").rename(tmp_path / "b.md")
    assert hash_skill(tmp_path)[0] != first


def test_identical_trees_hash_identically(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for directory in (a, b):
        directory.mkdir()
        (directory / "SKILL.md").write_text("# Same\n", encoding="utf-8")
        (directory / "refs").mkdir()
        (directory / "refs" / "x.md").write_text("body\n", encoding="utf-8")
    assert hash_skill(a) == hash_skill(b)


def test_directory_hash_of_empty_file_list():
    """An empty skill still has a well-defined hash, not an exception."""
    assert directory_hash([]) == "sha256:" + hashlib.sha256(b"").hexdigest()