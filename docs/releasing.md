# Release Process

> How to publish a new version of Voxtra to PyPI, from version bump to automated pipeline.

---

## Overview

Voxtra uses an **automated release pipeline** with human approval gates. Pushing a version tag triggers CI, builds the package, publishes to TestPyPI (with approval), verifies the install, then publishes to PyPI (with approval), and finally creates a GitHub Release.

```
Developer pushes tag
        │
        ▼
┌─────────────────────┐
│  Lint + Test        │  automatic
│  (Python 3.11/3.12) │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Build package      │  automatic
│  + version check    │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  🔒 Approve         │  manual (testpypi environment)
│  Publish to TestPyPI│
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Verify install     │  automatic
│  from TestPyPI      │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  🔒 Approve         │  manual (pypi environment)
│  Publish to PyPI    │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Create GitHub      │  automatic
│  Release + assets   │
└─────────────────────┘
```

---

## Step-by-Step Release

### 1. Bump the version

Update the version in **two places** — they must match:

- `pyproject.toml` → `version = "X.Y.Z"`
- `src/voxtra/__init__.py` → `__version__ = "X.Y.Z"`

```python
# pyproject.toml
version = "0.2.0"

# src/voxtra/__init__.py
__version__ = "0.2.0"
```

### 2. Update the changelog

Add a new section to `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [0.2.0] - 2026-04-01

### Added
- New feature X

### Changed
- Updated Y

### Fixed
- Bug Z
```

The release pipeline automatically extracts this section for the GitHub Release body.

### 3. Commit

```bash
git add pyproject.toml src/voxtra/__init__.py CHANGELOG.md
git commit -m "release: v0.2.0"
```

### 4. Tag and push

```bash
git tag -a v0.2.0 -m "v0.2.0 — Short description of the release"
git push origin main v0.2.0
```

This triggers the release pipeline in GitHub Actions.

### 5. Approve TestPyPI publish

1. Go to **GitHub → Actions** → find the running "Release & Publish" workflow
2. The **🧪 Publish to TestPyPI** job will be paused, waiting for approval
3. Click **Review deployments** → select `testpypi` → **Approve and deploy**
4. The package publishes to TestPyPI, then the verification step automatically installs it and checks the version

### 6. Approve PyPI publish

1. After TestPyPI verification passes, the **🚀 Publish to PyPI** job pauses
2. Click **Review deployments** → select `pypi` → **Approve and deploy**
3. The package publishes to PyPI

### 7. GitHub Release (automatic)

After PyPI publish succeeds, the pipeline automatically:
- Extracts release notes from `CHANGELOG.md`
- Creates a GitHub Release with the tag
- Attaches the `.whl` and `.tar.gz` build artifacts
- Marks it as a pre-release if the version contains `a`, `b`, or `rc`

---

## Version Format (PEP 440)

Python requires **PEP 440** compliant version strings. Using non-standard formats (e.g., `0.1.0-beta`) causes pip to normalize them unpredictably, breaking version checks.

### Valid formats

| Format | Meaning | Example |
|--------|---------|---------|
| `X.Y.ZaN` | Alpha N | `0.1.0a1` |
| `X.Y.ZbN` | Beta N | `0.1.0b2` |
| `X.Y.ZrcN` | Release candidate N | `0.1.0rc1` |
| `X.Y.Z` | Stable release | `0.1.0` |
| `X.Y.Z.postN` | Post-release fix | `0.1.0.post1` |
| `X.Y.Z.devN` | Development snapshot | `0.1.0.dev3` |

### Invalid formats (do NOT use)

| Format | Problem |
|--------|---------|
| `0.1.0-beta` | Pip normalizes to `0.1.0b0` — breaks tag matching |
| `0.1.0_beta` | Not a valid pre-release segment |
| `0.1.0beta` | Missing the version number suffix |
| `v0.1.0` | The `v` prefix is for git tags only, not the version field |

### Typical release progression

```
0.1.0a1  →  0.1.0a2  →  0.1.0b1  →  0.1.0b2  →  0.1.0rc1  →  0.1.0
```

---

## GitHub Environments Setup

The release pipeline uses GitHub **environments** for approval gates and secrets.

### Required environments

| Environment | Secrets | Protection Rules |
|-------------|---------|-----------------|
| `testpypi` | `TEST_PYPI_TOKEN` — API token from [test.pypi.org](https://test.pypi.org/manage/account/#api-tokens) | Required reviewer (at least 1) |
| `pypi` | `PYPI_TOKEN` — API token from [pypi.org](https://pypi.org/manage/account/#api-tokens) | Required reviewer (at least 1) |

### Setting up environments

1. Go to **GitHub repo → Settings → Environments**
2. Create environment `testpypi`:
   - Add secret `TEST_PYPI_TOKEN` with your TestPyPI API token
   - Under **Environment protection rules**, enable **Required reviewers** and add yourself
3. Create environment `pypi`:
   - Add secret `PYPI_TOKEN` with your PyPI API token
   - Under **Environment protection rules**, enable **Required reviewers** and add yourself

### Generating API tokens

**PyPI:**
1. Go to https://pypi.org/manage/account/#api-tokens
2. Click **Add API token**
3. Scope: **Entire account** (for first publish) or **Project: voxtra** (after first publish)
4. Copy the token (starts with `pypi-`)

**TestPyPI:**
1. Go to https://test.pypi.org/manage/account/#api-tokens
2. Same process as above

---

## Pipeline Details

The pipeline is defined in `.github/workflows/publish.yml` and consists of 6 jobs:

### Job 1: `ci` — Lint and test
- Runs on Python 3.11 and 3.12 (matrix)
- `ruff check src/ tests/` — Linting
- `pytest --tb=short -q` — Unit tests
- **Must pass** before build starts

### Job 2: `build` — Build package
- Runs `python -m build` to create sdist and wheel
- **Version check**: Compares the git tag against `pyproject.toml` version — fails if they don't match
- Uploads build artifacts for downstream jobs

### Job 3: `publish-testpypi` — Publish to TestPyPI
- **Requires human approval** (environment protection rule)
- Publishes using `pypa/gh-action-pypi-publish` with `TEST_PYPI_TOKEN`

### Job 4: `verify-testpypi` — Verify install
- Waits 30 seconds for the TestPyPI index to update
- Installs `voxtra==<version>` from TestPyPI
- Verifies `import voxtra; voxtra.__version__` matches the tag
- **Catches packaging bugs** before they reach PyPI

### Job 5: `publish-pypi` — Publish to PyPI
- **Requires human approval** (environment protection rule)
- Publishes using `pypa/gh-action-pypi-publish` with `PYPI_TOKEN`

### Job 6: `github-release` — Create GitHub Release
- Extracts release notes from `CHANGELOG.md` for the current version
- Creates a GitHub Release with the tag
- Attaches `.whl` and `.tar.gz` as release assets
- Automatically detects pre-releases (alpha/beta/rc)

---

## Troubleshooting

### Version mismatch error

```
Error: Version mismatch! Tag is v0.2.0 but pyproject.toml has 0.1.0
```

**Fix:** Ensure the tag matches the version in `pyproject.toml` exactly (without the `v` prefix).

### TestPyPI install fails

```
ERROR: No matching distribution found for voxtra==0.2.0
```

**Cause:** TestPyPI index hasn't updated yet. The pipeline waits 30 seconds, but sometimes it takes longer. Re-run the job.

### `__version__` mismatch

```
Installed version: 0.1.0 does not match tag v0.2.0
```

**Fix:** You forgot to update `src/voxtra/__init__.py`. Both `pyproject.toml` and `__init__.py` must have the same version.

### Package already exists on PyPI

```
400 Client Error: File already exists
```

**Cause:** This exact version was already published. PyPI does not allow overwriting. Bump to the next version.

### How to undo a bad tag

```bash
# Delete local tag
git tag -d v0.1.0-bad

# Delete remote tag
git push origin --delete v0.1.0-bad
```

---

## Quick Reference

```bash
# Full release in 4 commands:
vim pyproject.toml src/voxtra/__init__.py CHANGELOG.md  # bump version + changelog
git commit -am "release: v0.2.0"
git tag -a v0.2.0 -m "v0.2.0 — Description"
git push origin main v0.2.0
# Then approve testpypi → approve pypi in GitHub Actions
```
