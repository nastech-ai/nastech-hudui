"""Remote static publishing for NasTech Replay (PRD §22.1).

Builds a deployable static site from locally published replays and syncs it
to a git-backed static host (GitHub Pages, or any repo a static host serves).
Sync is explicit and disabled by default — nothing leaves the machine unless
the user configures a remote and triggers a sync.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.services.replay_exporter import default_replay_dir, get_replay_gallery

REMOTE_SETTINGS_FILE = "remote.json"
LAST_SYNC_FILE = "last_sync.json"
SITE_DIR = "site"
SITE_REPO_DIR = ".site-repo"

DEFAULT_REMOTE_SETTINGS = {
    "schema_version": "0.1",
    "enabled": False,
    "provider": "github-pages",
    "repo": "",
    "branch": "gh-pages",
    "base_url": "",
}

_OWNER_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


class PublishError(RuntimeError):
    """Raised when remote publishing cannot proceed."""


# ── Settings ────────────────────────────────────────────────────────────────

def get_remote_settings() -> dict:
    path = default_replay_dir() / REMOTE_SETTINGS_FILE
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    settings = {**DEFAULT_REMOTE_SETTINGS}
    for key in DEFAULT_REMOTE_SETTINGS:
        if key in data:
            settings[key] = data[key]
    settings["enabled"] = bool(settings["enabled"])
    settings["provider"] = "github-pages"
    return settings


def update_remote_settings(settings: dict) -> dict:
    current = get_remote_settings()
    next_settings = {
        **current,
        "enabled": bool(settings.get("enabled", current["enabled"])),
        "repo": str(settings.get("repo", current["repo"])).strip(),
        "branch": str(settings.get("branch", current["branch"])).strip() or "gh-pages",
        "base_url": str(settings.get("base_url", current["base_url"])).strip().rstrip("/"),
    }
    root = default_replay_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / REMOTE_SETTINGS_FILE
    path.write_text(json.dumps(next_settings, indent=2, sort_keys=True), encoding="utf-8")
    return next_settings


def _remote_url(repo: str) -> str:
    if _OWNER_REPO_RE.match(repo):
        return f"https://github.com/{repo}.git"
    return repo


def _pages_base_url(settings: dict) -> str:
    if settings["base_url"]:
        return settings["base_url"]
    repo = settings["repo"].removesuffix(".git")
    if _OWNER_REPO_RE.match(repo):
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}"
    return ""


# ── Site build ──────────────────────────────────────────────────────────────

def _unlisted_token(manifest: dict) -> str:
    digest = str(manifest.get("redacted_replay_hash") or "")
    token = digest.split(":", 1)[-1][:16]
    return token or str(manifest.get("replay_id") or "unlisted")


def _entry_site_path(manifest: dict) -> str:
    replay_id = str(manifest.get("replay_id") or "")
    if manifest.get("visibility") == "public":
        return f"runs/{replay_id}"
    return f"u/{_unlisted_token(manifest)}/{replay_id}"


# publish.json carries local filesystem paths — never ship it
_SITE_FILES = ["replay.html", "replay.redacted.json", "receipt.json", "share-card.png", "replay.md", "fork.json"]


def _write_site_index(site_dir: Path, public_entries: list[dict]) -> None:
    cards = []
    for entry in public_entries:
        title = html.escape(str(entry.get("title") or entry.get("replay_id") or "Untitled replay"))
        href = html.escape(f"{_entry_site_path(entry)}/replay.html")
        receipt_hash = html.escape(str(entry.get("receipt_hash") or "pending"))
        cards.append(
            f"<article><h2><a href=\"{href}\">{title}</a></h2>"
            f"<small>views {entry.get('view_count', 0)} · forks {entry.get('fork_count', 0)}</small>"
            f"<code>{receipt_hash}</code></article>"
        )
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NasTech Replay Gallery</title>
  <style>
    body {{ margin:0; font-family:system-ui,sans-serif; background:#071211; color:#d7fffb; }}
    main {{ max-width:1080px; margin:0 auto; padding:32px; }}
    h1 {{ color:#5ef6d2; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
    article {{ border:1px solid #1f4f4a; background:#0c2220; padding:16px; }}
    h2 {{ margin:0 0 8px; font-size:18px; }}
    small, code {{ color:#95aaa7; display:block; margin:8px 0; word-break:break-all; }}
    a {{ color:#5ef6d2; }}
  </style>
</head>
<body>
  <main>
    <h1>NasTech Replay Gallery</h1>
    <p>Run receipts published from NasTech Replay. All artifacts are redacted in Safe Share Mode.</p>
    <section class="grid">{''.join(cards) or '<article><h2>No published replays</h2></article>'}</section>
  </main>
</body>
</html>
"""
    (site_dir / "index.html").write_text(content, encoding="utf-8")


def build_site() -> dict:
    """Assemble the deployable static site from locally published replays."""
    root = default_replay_dir()
    site_dir = root / SITE_DIR
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    # Keep GitHub Pages from running the artifacts through Jekyll
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    gallery = get_replay_gallery()
    entries = [entry for entry in gallery.get("entries", []) if isinstance(entry, dict)]
    site_entries = []
    for entry in entries:
        visibility = entry.get("visibility")
        replay_id = str(entry.get("replay_id") or "")
        if visibility not in {"public", "unlisted"} or not replay_id:
            continue
        source_dir = root / visibility / replay_id
        if not source_dir.exists():
            continue
        target_dir = site_dir / _entry_site_path(entry)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in _SITE_FILES:
            src = source_dir / name
            if src.exists():
                shutil.copyfile(src, target_dir / name)
        site_entries.append(
            {
                "replay_id": replay_id,
                "title": entry.get("title"),
                "visibility": visibility,
                "path": f"{_entry_site_path(entry)}/replay.html",
            }
        )

    public_entries = [entry for entry in entries if entry.get("visibility") == "public"]
    _write_site_index(site_dir, public_entries)
    return {
        "site_dir": str(site_dir),
        "entries": site_entries,
        "public_count": sum(1 for e in site_entries if e["visibility"] == "public"),
        "unlisted_count": sum(1 for e in site_entries if e["visibility"] == "unlisted"),
    }


# ── Git sync ────────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise PublishError(f"git {args[0]} failed: {detail}")
    return result


def _prepare_site_repo(root: Path, remote: str, branch: str) -> Path:
    repo_dir = root / SITE_REPO_DIR
    if (repo_dir / ".git").exists():
        _run_git(["remote", "set-url", "origin", remote], repo_dir)
        try:
            _run_git(["fetch", "origin", branch], repo_dir)
            _run_git(["reset", "--hard", "FETCH_HEAD"], repo_dir)
        except PublishError:
            pass  # branch may not exist remotely yet — first push will create it
        return repo_dir
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    try:
        _run_git(["clone", "--depth", "1", "--branch", branch, remote, str(repo_dir)], root)
    except PublishError:
        repo_dir.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "-b", branch], repo_dir)
        _run_git(["remote", "add", "origin", remote], repo_dir)
    return repo_dir


def _mirror_into_repo(site_dir: Path, repo_dir: Path) -> None:
    for child in repo_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in site_dir.iterdir():
        target = repo_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copyfile(child, target)


def sync_remote() -> dict:
    """Build the static site and push it to the configured git remote."""
    settings = get_remote_settings()
    if not settings["enabled"]:
        raise PublishError("Remote publishing is disabled. Enable it in Replay settings first.")
    if not settings["repo"]:
        raise PublishError("No remote repository configured.")
    if shutil.which("git") is None:
        raise PublishError("git is not available on PATH.")

    root = default_replay_dir()
    site = build_site()
    remote = _remote_url(settings["repo"])
    branch = settings["branch"]
    repo_dir = _prepare_site_repo(root, remote, branch)
    _mirror_into_repo(root / SITE_DIR, repo_dir)

    _run_git(["add", "-A"], repo_dir)
    porcelain = _run_git(["status", "--porcelain"], repo_dir).stdout.strip()
    up_to_date = not porcelain
    if not up_to_date:
        _run_git(
            [
                "-c", "user.name=NasTech Replay",
                "-c", "user.email=replay@nastech-hud.local",
                "commit",
                "-m", f"Sync NasTech Replay gallery ({site['public_count']} public, {site['unlisted_count']} unlisted)",
            ],
            repo_dir,
        )
        _run_git(["push", "-u", "origin", branch], repo_dir)
    commit = _run_git(["rev-parse", "HEAD"], repo_dir).stdout.strip()

    base_url = _pages_base_url(settings)
    entries = [
        {**entry, "url": f"{base_url}/{entry['path']}" if base_url else entry["path"]}
        for entry in site["entries"]
    ]
    status = {
        "ok": True,
        "up_to_date": up_to_date,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "branch": branch,
        "remote": remote,
        "base_url": base_url,
        "index_url": f"{base_url}/index.html" if base_url else "index.html",
        "public_count": site["public_count"],
        "unlisted_count": site["unlisted_count"],
        "entries": entries,
    }
    (root / LAST_SYNC_FILE).write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    return status


def remote_status() -> dict:
    settings = get_remote_settings()
    last_sync = None
    path = default_replay_dir() / LAST_SYNC_FILE
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                last_sync = loaded
        except (json.JSONDecodeError, OSError):
            last_sync = None
    return {
        "settings": settings,
        "base_url": _pages_base_url(settings),
        "git_available": shutil.which("git") is not None,
        "last_sync": last_sync,
    }
