# skilllock

**A lockfile for Agent Skills: pin the version, verify the content, refuse the surprise.**

[![CI](https://github.com/NPLMSHJTR/skilllock/actions/workflows/ci.yml/badge.svg)](https://github.com/NPLMSHJTR/skilllock/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)
![spec](https://img.shields.io/badge/spec-v1-blue)

Installing a skill today usually means cloning a repository at whatever `main`
points to. Three months later the same install produces different content, and
there is no record of what you actually had.

`skilllock` records it. A `skilllock.toml` pins each skill to an immutable
revision, stores a hash of every file, and verifies the content before the skill
is used.

```console
$ skilllock verify

FAIL csv-profile
       content differs: SKILL.md
       directory hash mismatch: lockfile says sha256:fb14b80e9c43…,
                                content hashes to sha256:4a80e433e2c4…

0/1 verified
```

## What it actually catches

A skill is instructions for an agent. So an added line is not an added line; it
may be an added instruction. This is the failure the hash exists to find:

```console
$ echo "Ignore all previous instructions." >> skills/csv-profile/SKILL.md
$ skilllock verify

FAIL csv-profile
       content differs: SKILL.md
```

And a file that was never locked at all — nobody reviewed it, but the agent will
still read it:

```console
$ echo "exfiltrate secrets" > skills/csv-profile/EXTRA.md
$ skilllock verify

FAIL csv-profile
       unlisted file present on disk: EXTRA.md
```

Both are refused rather than warned about, which is the only useful behaviour
here.

## Install

```bash
pipx install git+https://github.com/NPLMSHJTR/skilllock
```

Or from source, with no dependencies. Python 3.9+; `tomllib` is used when
available and a small parser covers 3.9 and 3.10.

```bash
git clone https://github.com/NPLMSHJTR/skilllock
cd skilllock
python -m skilllock --help
```

## Use

```bash
skilllock lock    --source github:owner/repo --revision <full-sha>
skilllock verify                       # check content against the lockfile
skilllock check                        # content plus dependency constraints
skilllock show                         # summarise what is locked
```

Exit codes:

| code | meaning |
| --- | --- |
| `0` | locked, or everything verified |
| `1` | verification failed, or the lockfile is invalid |
| `2` | usage error, or no `skills/` directory |

## Required: normalise line endings

This is not a tip, it is a prerequisite. Hashes are over bytes, so a file with
CRLF hashes differently from the same file with LF.

Put this in `.gitattributes` at the project root:

```gitattributes
* text=auto eol=lf
```

Without it, a lockfile created on Linux fails verification on a Windows checkout
that used `autocrlf=true`, and the error looks like tampering. The reasoning is in
[spec/lockfile-v1.md](spec/lockfile-v1.md) section 5.5.

## The format is the product

[`spec/lockfile-v1.md`](spec/lockfile-v1.md) is the specification. This
implementation is one consumer of it, not the definition. If you want to read
these files from a different language or tool, that document is what you conform
to, and [`tests/test_conformance.py`](tests/test_conformance.py) is the list of
behaviours a conforming reader must have.

A deliberately small example:

```toml
version = 1

[[skill]]
name = "csv-profile"
source = "github:NPLMSHJTR/skillvet"
revision = "a83cd98224fd59182740035df0a9bb9c93589ca065725afa24509544f6ba57e0"
path = "skills/csv-profile"
hash = "sha256:fb14b80e9c43e9ec601100cfb918696f569370da280bd63662f225c41329cb35"

  [[skill.file]]
  path = "SKILL.md"
  hash = "sha256:a83cd98224fd59182740035df0a9bb9c93589ca065725afa24509544f6ba57e0"
```

## Design decisions worth knowing

**Both a directory hash and per-file hashes.** Redundant on purpose. The directory
hash makes "is this the same skill" one comparison; the per-file hashes make
"which file changed" answerable. An error that names the file is worth the extra
field.

**The directory hash is reproducible by hand.** It is a `sha256sum`-shaped
manifest, so when someone reports a mismatch on a machine without this tool:

```bash
find . -type f | sort | xargs sha256sum | sha256sum
```

That is the same number. Debugging a hash mismatch should not require installing
the tool that produced it.

**Branch names are rejected as revisions.** A lockfile that says `main` does not
lock anything. The tool refuses it rather than writing a file that looks like a
lockfile and is not.

**No install-time URLs, no post-install scripts.** A `source` names a repository,
not a downloadable artifact, and installing a skill never executes anything. A
lockfile that can point at an arbitrary URL is a supply chain vulnerability
disguised as a convenience.

**Unknown versions are refused before anything else is read.** Field names may
mean something different in a future version, so parsing the body first produces a
confusing error for a file that should be rejected outright.

## What it does not do

- **No real dependency solver.** Three constraint forms (`*`, `=1.2.3`, `^1.2`),
  no backtracking, no version intersection. A lockfile records the result of
  resolution; how a tool resolves is out of scope, so two implementations can
  disagree and still interoperate on the file.
- **No fetching.** This tool does not download skills. It verifies what is on
  disk against what is recorded. Fetching is a separate concern with a separate
  threat model.
- **No signing in version 1.** The field is reserved. Adding a signature scheme
  half-designed is worse than leaving it out.
- **No dotfile support.** A skill shipping `.github/workflows/ci.yml` will have
  that file ignored by the hash. Documented in the spec, section 7.

## In CI

```yaml
- run: skilllock check
```

Fails the build when locked content changed. That is the moment you want to know,
not the first time an agent behaves strangely.

## Docs

| file | contents |
| --- | --- |
| [spec/lockfile-v1.md](spec/lockfile-v1.md) | the format specification |
| [docs/why.md](docs/why.md) | the threat model, and why warnings are not enough |

## Status

Version 0.1.0, format version 1 (draft until 1.0).

78 tests, including one per conformance point in spec section 8.

## License

MIT.