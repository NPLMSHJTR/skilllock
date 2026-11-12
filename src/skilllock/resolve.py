"""Version constraints, exactly the three forms version 1 defines.

The narrow scope is deliberate and documented in the spec, section 7. A general
solver is a different project; what a lockfile needs is the ability to say
"==1.2.3" and "same major" and to refuse anything it cannot evaluate rather than
silently accepting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class ConstraintError(ValueError):
    """A constraint this tool cannot evaluate."""


@dataclass(frozen=True, order=True)
class Version:
    """Ordered so `>=` and `<` work, which the caret constraint needs."""

    major: int
    minor: int = 0
    patch: int = 0

    @classmethod
    def parse(cls, text: str) -> "Version | None":
        text = text.strip().lstrip("vV")
        match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?", text)
        if not match:
            return None
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2) or 0),
            patch=int(match.group(3) or 0),
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def satisfies(version_text: str | None, constraint: str) -> bool:
    """Whether a declared version satisfies a constraint.

    A skill with no declared version satisfies only `*`. This is spec section 4.6
    and it is intentional: guessing a version for an unversioned skill is how a
    constraint quietly stops constraining anything.
    """
    constraint = constraint.strip()
    if constraint == "*":
        return True

    version = Version.parse(version_text) if version_text else None

    if constraint.startswith("="):
        wanted = Version.parse(constraint[1:])
        if wanted is None:
            raise ConstraintError(f"cannot parse the version in `{constraint}`")
        if version is None:
            return False
        return version == wanted

    if constraint.startswith("^"):
        wanted = Version.parse(constraint[1:])
        if wanted is None:
            raise ConstraintError(f"cannot parse the version in `{constraint}`")
        if version is None:
            return False
        return version.major == wanted.major and version >= wanted

    raise ConstraintError(
        f"unsupported constraint `{constraint}`; version 1 defines `*`, `=1.2.3` "
        "and `^1.2`"
    )


def check_dependencies(entries: dict) -> list[str]:
    """Return a list of problems with a set of resolved entries.

    `entries` maps skill name to (declared version, list of Dependency).
    """
    problems: list[str] = []
    for name, (declared_version, dependencies) in sorted(entries.items()):
        for dependency in dependencies:
            if dependency.name not in entries:
                problems.append(
                    f"{name}: dependency `{dependency.name}` is not in the "
                    "resolved set"
                )
                continue
            target_version, _ = entries[dependency.name]
            try:
                ok = satisfies(target_version, dependency.constraint)
            except ConstraintError as exc:
                problems.append(f"{name} -> {dependency.name}: {exc}")
                continue
            if not ok:
                problems.append(
                    f"{name} -> {dependency.name}: version {target_version!r} "
                    f"does not satisfy `{dependency.constraint}`"
                )
    return problems