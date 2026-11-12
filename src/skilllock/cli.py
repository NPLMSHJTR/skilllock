"""Command line interface.

    skilllock lock    [--skills DIR] [--source NAME] [--revision SHA]
    skilllock verify  [--skills DIR]
    skilllock check   [--skills DIR]
    skilllock show

Exit codes:
    0  success / everything verified
    1  verification failed
    2  usage error, or no lockfile
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .hashing import hash_skill
from .lockfile import FILENAME, Lockfile, SkillEntry, FileEntry, LockfileError, read, write
from .resolve import ConstraintError, check_dependencies, satisfies
from .verify import verify_all


def _paint(text: str, code: str, disabled: bool) -> str:
    return text if disabled else f"\033[{code}m{text}\033[0m"


def _skill_dirs(skills_root: Path) -> list[Path]:
    if not skills_root.is_dir():
        return []
    return sorted(
        {p.parent for p in skills_root.rglob("SKILL.md") if not any(
            part.startswith(".") for part in p.relative_to(skills_root).parts
        )}
    )


def _declared_version(skill_dir: Path) -> str | None:
    """Read metadata.version from the frontmatter, without a YAML dependency."""
    import re

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]

    in_metadata = False
    for line in block.splitlines():
        if re.match(r"^metadata\s*:", line):
            in_metadata = True
            continue
        if in_metadata:
            if line and not line.startswith((" ", "\t")):
                in_metadata = False
                continue
            match = re.match(r"^\s+version\s*:\s*[\"']?([^\"'\s]+)", line)
            if match:
                return match.group(1)
    return None


def _declared_dependencies(skill_dir: Path) -> list[tuple[str, str]]:
    """Read dependencies from a `dependencies:` block, if present.

    Kept intentionally simple: a list of `name@constraint` strings. A richer
    syntax can wait until someone needs it.
    """
    import re

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return []
    lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
    found: list[tuple[str, str]] = []
    in_block = False
    for line in lines:
        if re.match(r"^dependencies\s*:\s*$", line):
            in_block = True
            continue
        if in_block:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            match = re.match(r"^\s+-\s*[\"']?([^\"'\s]+)", line)
            if match:
                spec = match.group(1)
                if "@" in spec:
                    name, _, constraint = spec.partition("@")
                    found.append((name, constraint))
                else:
                    found.append((spec, "*"))
    return found


def cmd_lock(args: argparse.Namespace) -> int:
    project = Path(args.path)
    skills_root = project / args.skills
    directories = _skill_dirs(skills_root)

    if not directories:
        print(f"skilllock: no skills found under {skills_root}", file=sys.stderr)
        return 2

    lock = Lockfile()
    for directory in directories:
        digest, files = hash_skill(directory)
        lock.skills.append(
            SkillEntry(
                name=directory.name,
                source=args.source,
                revision=args.revision,
                path=str(directory.relative_to(project)).replace("\\", "/"),
                hash=digest,
                files=[FileEntry(path=f.path, hash=f.digest) for f in files],
            )
        )

    try:
        from .lockfile import validate

        validate(lock)
    except LockfileError as exc:
        print(f"skilllock: {exc}", file=sys.stderr)
        return 1

    target = project / FILENAME
    write(lock, target)
    total_files = sum(len(s.files) for s in lock.skills)
    print(f"wrote {target}")
    print(f"  {len(lock.skills)} skill(s), {total_files} file(s) hashed")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    project = Path(args.path)
    target = project / FILENAME
    no_color = args.no_color
    red = lambda t: _paint(t, "31", no_color)  # noqa: E731
    green = lambda t: _paint(t, "32", no_color)  # noqa: E731
    dim = lambda t: _paint(t, "2", no_color)  # noqa: E731

    if not target.exists():
        print(f"skilllock: no {FILENAME} found in {project}", file=sys.stderr)
        return 2

    try:
        lock = read(target)
    except LockfileError as exc:
        print(f"skilllock: {exc}", file=sys.stderr)
        return 1

    skills_root = project / args.skills
    mapping = {d.name: d for d in _skill_dirs(skills_root)}
    results = verify_all(mapping, lock.skills)

    if args.format == "json":
        payload = {
            "lockfile": str(target),
            "ok": all(r.ok for r in results),
            "skills": [
                {"name": r.skill, "ok": r.ok, "checked": r.checked, "problems": r.problems}
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload["ok"] else 1

    for result in results:
        if result.ok:
            print(f"{green('PASS')} {result.summary()}")
        else:
            print(f"{red('FAIL')} {result.skill}")
            for problem in result.problems:
                print(f"       {dim(problem)}")

    ok = sum(1 for r in results if r.ok)
    print()
    if ok == len(results):
        print(green(f"all {ok} skill(s) verified"))
        return 0
    print(red(f"{ok}/{len(results)} verified"))
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    """Verify integrity and dependency constraints together."""
    project = Path(args.path)
    target = project / FILENAME
    if not target.exists():
        print(f"skilllock: no {FILENAME} found in {project}", file=sys.stderr)
        return 2

    try:
        lock = read(target)
    except LockfileError as exc:
        print(f"skilllock: {exc}", file=sys.stderr)
        return 1

    skills_root = project / args.skills
    mapping = {d.name: d for d in _skill_dirs(skills_root)}
    results = verify_all(mapping, lock.skills)
    integrity_ok = all(r.ok for r in results)

    resolved: dict[str, tuple[str | None, list]] = {}
    for entry in lock.skills:
        directory = mapping.get(entry.name)
        version = _declared_version(directory) if directory else None
        declared = _declared_dependencies(directory) if directory else []
        from .lockfile import Dependency

        resolved[entry.name] = (
            version,
            [Dependency(name=n, constraint=c) for n, c in declared],
        )

    problems = check_dependencies(resolved)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": integrity_ok and not problems,
                    "integrity": [
                        {"name": r.skill, "ok": r.ok, "problems": r.problems}
                        for r in results
                    ],
                    "dependency_problems": problems,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for result in results:
            mark = "PASS" if result.ok else "FAIL"
            print(f"{mark} {result.summary()}")
            for problem in result.problems:
                print(f"       {problem}")
        for problem in problems:
            print(f"DEPS {problem}")

    return 0 if (integrity_ok and not problems) else 1


def cmd_show(args: argparse.Namespace) -> int:
    project = Path(args.path)
    target = project / FILENAME
    if not target.exists():
        print(f"skilllock: no {FILENAME} found in {project}", file=sys.stderr)
        return 2

    try:
        lock = read(target)
    except LockfileError as exc:
        print(f"skilllock: {exc}", file=sys.stderr)
        return 1

    print(f"{FILENAME}: {len(lock.skills)} skill(s), format version {lock.version}")
    for skill in sorted(lock.skills, key=lambda s: s.name):
        print(f"  {skill.name}")
        print(f"    source   {skill.source}")
        print(f"    revision {skill.revision}")
        print(f"    files    {len(skill.files)}")
        if skill.dependencies:
            deps = ", ".join(f"{d.name}{d.constraint}" for d in skill.dependencies)
            print(f"    depends  {deps}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skilllock",
        description="A lockfile for Agent Skills: pin versions, verify content, "
        "record the resolved dependency closure.",
    )
    parser.add_argument("--version", action="version", version=f"skilllock {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("path", nargs="?", default=".", help="project root")
    common.add_argument("--skills", default="skills", help="skills directory")
    common.add_argument("--no-color", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_lock = sub.add_parser("lock", parents=[common], help="write a lockfile")
    p_lock.add_argument(
        "--source",
        default="path:.",
        help="source identifier recorded in the lockfile (default: path:.)",
    )
    p_lock.add_argument(
        "--revision",
        default="local",
        help="immutable revision recorded in the lockfile (default: local)",
    )
    p_lock.set_defaults(func=cmd_lock)

    p_verify = sub.add_parser("verify", parents=[common], help="verify content")
    p_verify.add_argument("--format", choices=("text", "json"), default="text")
    p_verify.set_defaults(func=cmd_verify)

    p_check = sub.add_parser(
        "check", parents=[common], help="verify content and dependencies"
    )
    p_check.add_argument("--format", choices=("text", "json"), default="text")
    p_check.set_defaults(func=cmd_check)

    p_show = sub.add_parser("show", parents=[common], help="summarise the lockfile")
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConstraintError as exc:
        print(f"skilllock: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())