# skilllock file format, version 1

**Status:** draft. Version 1 is not final until the reference implementation
ships 1.0.

This document is the specification. The reference implementation in `src/` is one
consumer of it, not the definition. If you implement this format elsewhere, this
file is what you conform to.

---

## 1. Purpose

A `skilllock.toml` file records exactly which skills, at which versions, with
which content, a project depends on. Its job is to make an environment
reproducible: given the lockfile and network access to the recorded sources, a
different machine produces byte-identical skill content.

It solves three problems that plain copying does not:

1. **Version pinning.** A skill fetched from a branch can change under you. A
   lockfile records the exact revision.
2. **Integrity.** A locked file records the hash of its content. A skill whose
   content changed after locking is rejected rather than silently accepted.
3. **Transitive closure.** A skill can require other skills. The lockfile records
   the resolved closure, not just the direct dependencies, so installation does
   not require re-resolving.

What it explicitly does not do: fetch from arbitrary URLs at install time. Section
6 covers why.

---

## 2. File name and format

The file is named `skilllock.toml` and lives at the project root.

It is TOML. The choice is deliberate: TOML is readable without tooling, has no
significant whitespace, and is already the format of `pyproject.toml` and
`Cargo.toml`, so the audience has a parser installed.

---

## 3. Top-level structure

```toml
version = 1

[[skill]]
name = "example-review"
source = "github:NPLMSHJTR/skillport"
revision = "b037f129a4c3d5e6f708192a3b4c5d6e7f8091a2"
path = "skills/example-review"
hash = "sha256:8f14e45fceea167a5a36dedd4bea2543..."

  [[skill.file]]
  path = "SKILL.md"
  hash = "sha256:9e107d9d372bb6826bd81d3542a41909..."

  [[skill.file]]
  path = "references/severity.md"
  hash = "sha256:3c59dc048e8850243be807c08075d6a5..."

  [[skill.dependency]]
  name = "changelog"
  constraint = "^1.0"
```

Three tables exist: one `version` integer and an array of `skill` tables. Each
skill may contain nested `file` and `dependency` arrays.

---

## 4. Fields

### 4.1 `version`

| property | value |
| --- | --- |
| type | integer |
| required | yes |
| allowed | `1` |

A consumer must reject a lockfile whose `version` it does not implement, with an
error that names the versions it does support. Silently proceeding on an unknown
version is how a format breaks without anyone noticing.

### 4.2 `[[skill]]`

| field | type | required | meaning |
| --- | --- | --- | --- |
| `name` | string | yes | The skill's identifier. Must equal the resolved directory name. |
| `source` | string | yes | Where it came from. See 4.3. |
| `revision` | string | yes | Immutable revision at the source: a full commit SHA, or a release tag. |
| `path` | string | yes | Path inside the source at that revision. |
| `hash` | string | yes | Hash of the whole skill directory. See section 5. |

`name` must be unique within one lockfile. Two entries with the same name are an
error, not a merge.

`revision` must be immutable. A branch name is not a valid revision and a consumer
must reject one, because a branch name in a lockfile defeats the purpose of having
a lockfile.

### 4.3 `source` forms

| form | example | notes |
| --- | --- | --- |
| `github:owner/repo` | `github:NPLMSHJTR/skillport` | The only form version 1 requires support for. |
| `git:https://host/path` | `git:https://git.example.com/skills.git` | Optional. A consumer may reject it. |
| `path:./relative` | `path:./vendor/skills` | Local directory. `revision` must be the literal string `"local"`. |

Any other prefix is an error in version 1. Extending the scheme requires a new
lockfile version, because a consumer that does not understand a source form cannot
install it and must not pretend otherwise.

`path:` exists so that vendored skills and monorepos can be locked without a
network fetch. A `path:` entry's hash is still verified.

### 4.4 `[[skill.file]]`

| field | type | required | meaning |
| --- | --- | --- | --- |
| `path` | string | yes | Path relative to the skill root, with forward slashes. |
| `hash` | string | yes | Hash of this file's content. |

The file list must be complete: every file the skill contains, except those
excluded by section 5.2. A consumer verifying a skill compares the file list
first and then each hash, so an unlisted extra file is a verification failure.

### 4.5 `[[skill.dependency]]`

| field | type | required | meaning |
| --- | --- | --- | --- |
| `name` | string | yes | The depended-on skill's name. |
| `constraint` | string | yes | A version constraint. See 4.6. |

A dependency that is not itself present as a `[[skill]]` entry in the same
lockfile is an **error**. The lockfile records the resolved closure; a missing
entry means the lockfile is incomplete, and a consumer must not resolve it at
install time.

### 4.6 `constraint`

Version 1 defines three constraint forms, chosen because they cover most real use
and can be evaluated without a dependency graph solver:

| form | meaning |
| --- | --- |
| `*` | any version |
| `=1.2.3` | exactly this version |
| `^1.2` | same major, greater or equal |

Version comparison is over the skill's own declared version, taken from the
`metadata.version` field of its `SKILL.md` frontmatter. A skill with no declared
version satisfies only `*`. This is a deliberate limitation: see section 7.

---

## 5. Hashing

### 5.1 Algorithm

Hashes are written as `sha256:<lowercase hex>`. SHA-256 is required in version 1.
A future version may allow others by prefix.

### 5.2 What is excluded

The following are excluded from both the per-file list and the directory hash:

- `.git/` and any other VCS directory
- `__pycache__/`, `*.pyc`, `*.pyo`
- `.DS_Store`, `Thumbs.db`
- Any file whose name begins with a dot **except** `SKILL.md`, which is a
  legitimate skill file

Excluding dotfiles is a pragmatic choice: editors and OSes drop `.DS_Store` and
swap files into directories, and a lockfile that changes because someone opened a
folder in Finder is noise.

### 5.3 Both hashes are required

The directory hash and the per-file hashes are redundant by design.

The directory hash makes "is this the same skill" a single comparison. The
per-file hashes make "which file changed" answerable, which is the difference
between an error message that helps and one that does not.

### 5.4 Directory hash construction

The directory hash is computed over exactly this canonical form:

1. Sort file paths lexicographically by their UTF-8 byte sequence.
2. For each file, form the line `<hex-digest>  <path>\n` — two spaces, the path
   with forward slashes, then a newline.
3. Concatenate all lines in sorted order, encoded UTF-8.
4. SHA-256 the result.

This is the same shape as a `sha256sum` manifest, for the same reason: it can be
reproduced by hand with standard tools, which matters when someone is debugging a
hash mismatch on a machine where your tool is not installed.

### 5.5 Line endings are not normalised

**This is a real cross-platform hazard and it is deliberate.**

`hash_file` hashes the bytes on disk. A file with LF endings and the same file
with CRLF endings produce different hashes, so a lockfile created on Linux will
fail verification on a Windows checkout that used `core.autocrlf=true`.

The alternative — normalising line endings before hashing — was rejected because
it would stop the hash from detecting a file that was converted in transit, which
is exactly the kind of silent content change the hash exists to catch.

The mitigation is repository configuration, not tool behaviour:

```gitattributes
* text=auto eol=lf
```

With that in place, every checkout produces LF regardless of platform, and the
hash is stable. This is stated in the README as a required step, not an optional
tip, because the failure mode otherwise is a confusing CI error that looks like
tampering.

A future version may add a `normalise = "line-endings"` flag per entry, so a
project can opt into the other trade-off.

---

## 6. What the format deliberately omits

**No install-time URLs.** A `source` names a repository, not a downloadable
artifact. Fetching a tarball from an arbitrary URL recorded in a file is a supply
chain vulnerability: whoever can write the lockfile can point it anywhere.

**No post-install scripts.** Skills are instructions, but installing one should not
execute anything. A locked skill is fetched and verified; nothing runs.

**No signature field in version 1.** Signing would be valuable and the field is
reserved, but adding it half-designed is worse than leaving it out. A version 2
that adds `signature` and a `signing_key` table is the likely path.

**No resolution algorithm.** The format records the result of resolution. How a
tool decides which version to pick is out of scope, so two implementations can
disagree on resolution and still interoperate on the file.

---

## 7. Known limitations

Stated plainly, because a spec that claims to solve everything gets ignored by the
people who notice it does not.

**Dependencies are not a real solver.** The `^` constraint only means "same
major". There is no backtracking, no version intersection, no handling of two
dependencies requiring incompatible versions of a third. A real package manager
needs a real solver; this format is designed to be readable and implementable in
an afternoon.

**A skill's version comes from its own frontmatter.** If an author never bumps
`metadata.version`, every revision still reports the same version, and a `^`
constraint will happily accept a breaking change. The mitigations are `=` and the
integrity hashes, which do catch it — but only after a `lock` run, not at resolve
time.

**No deduplication across sources.** The same skill locked from two sources is two
entries. Version 1 rejects duplicate names, so this cannot currently arise.

**Dotfile exclusion is a real hole.** A skill that legitimately ships
`.github/workflows/ci.yml` will have that file ignored by the hash. If this becomes
a problem, a whitelist of allowed dot-paths is the fix.

---

## 8. Conformance

A consumer conforms to version 1 if it:

1. Rejects an unknown `version` value with a clear error.
2. Rejects an entry missing any required field.
3. Rejects a `revision` that is a branch name rather than an immutable identifier.
4. Verifies the directory hash and every per-file hash before declaring success.
5. Fails when a file exists on disk that is not listed.
6. Fails when a listed dependency has no corresponding `[[skill]]` entry.
7. Never executes anything while installing.

The reference test suite for these points is in `tests/test_conformance.py`.

---

## 9. Example

A complete, realistic file:

```toml
version = 1

[[skill]]
name = "example-review"
source = "github:NPLMSHJTR/skillport"
revision = "b037f129a4c3d5e6f708192a3b4c5d6e7f8091a2"
path = "skills/example-review"
hash = "sha256:1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809"

  [[skill.file]]
  path = "SKILL.md"
  hash = "sha256:9e107d9d372bb6826bd81d3542a41909"

  [[skill.file]]
  path = "references/severity.md"
  hash = "sha256:3c59dc048e8850243be807c08075d6a5"

[[skill]]
name = "changelog"
source = "path:./vendor/skills"
revision = "local"
path = "changelog"
hash = "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
```

Note the `path:` entry uses `revision = "local"`, and both entries list their
files explicitly.