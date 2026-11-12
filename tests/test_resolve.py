"""Tests for version constraints: only the three forms the spec defines."""

from __future__ import annotations

import pytest

from skilllock.lockfile import Dependency
from skilllock.resolve import ConstraintError, Version, check_dependencies, satisfies


def test_version_parsing():
    assert Version.parse("1.2.3") == Version(1, 2, 3)
    assert Version.parse("v1.2") == Version(1, 2, 0)
    assert Version.parse("1") == Version(1, 0, 0)
    assert Version.parse("1.2.3-beta.1") == Version(1, 2, 3)
    assert Version.parse("not a version") is None


def test_wildcard_always_satisfies():
    assert satisfies(None, "*")
    assert satisfies("1.0.0", "*")


def test_exact_match():
    assert satisfies("1.2.3", "=1.2.3")
    assert not satisfies("1.2.4", "=1.2.3")
    assert not satisfies(None, "=1.2.3")


def test_caret_same_major():
    assert satisfies("1.2.0", "^1.0")
    assert satisfies("1.9.9", "^1.0")
    assert not satisfies("2.0.0", "^1.0")
    assert not satisfies("0.9.0", "^1.0")
    assert not satisfies(None, "^1.0")


def test_caret_requires_at_least_the_floor():
    assert not satisfies("1.0.0", "^1.5")


def test_unsupported_constraint_raises():
    with pytest.raises(ConstraintError, match="unsupported constraint"):
        satisfies("1.0.0", ">=1.0")
    with pytest.raises(ConstraintError, match="unsupported constraint"):
        satisfies("1.0.0", "~1.0")


def test_malformed_constraint_raises():
    with pytest.raises(ConstraintError, match="cannot parse"):
        satisfies("1.0.0", "=abc")
    with pytest.raises(ConstraintError, match="cannot parse"):
        satisfies("1.0.0", "^abc")


def test_unversioned_satisfies_only_wildcard():
    """A skill with no version cannot satisfy a version constraint."""
    assert satisfies(None, "*")
    assert not satisfies(None, "^1.0")
    assert not satisfies(None, "=1.0.0")


def test_check_dependencies_clean():
    entries = {
        "a": ("1.2.0", [Dependency("b", "^1.0")]),
        "b": ("1.9.0", []),
    }
    assert check_dependencies(entries) == []


def test_check_dependencies_missing():
    entries = {"a": ("1.0.0", [Dependency("gone", "*")])}
    problems = check_dependencies(entries)
    assert any("is not in the resolved set" in p for p in problems)


def test_check_dependencies_version_mismatch():
    entries = {
        "a": ("1.0.0", [Dependency("b", "^2.0")]),
        "b": ("1.5.0", []),
    }
    problems = check_dependencies(entries)
    assert any("does not satisfy" in p for p in problems)


def test_check_dependencies_bad_constraint():
    entries = {
        "a": ("1.0.0", [Dependency("b", ">=1.0")]),
        "b": ("1.5.0", []),
    }
    problems = check_dependencies(entries)
    assert any("unsupported constraint" in p for p in problems)