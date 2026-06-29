"""Write-path tests for the profile editing API (backend/api/profiles.py).

``PUT /api/profiles/{name}/edit`` rewrites a profile's ``config.yaml`` and
``SOUL.md`` via an atomic write under a lock. These cover the corruption- and
safety-sensitive surface: round-trip persistence, valid YAML output, path
traversal / name validation, the "model/provider cannot be silently cleared"
guards, and that rejected edits never touch the on-disk config.

``default_nastech_dir()`` reads ``NASTECH_HOME`` at call time, so the profile
tree is built under a tmp dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from backend.api.profiles import (
    ProfileCompressionEdit,
    ProfileEditBody,
    ProfileModelEdit,
    get_profile_edit,
    update_profile_edit,
)
from backend.collectors.utils import load_yaml


@pytest.fixture
def nastech_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("NASTECH_HOME", str(tmp_path))
    return tmp_path


def _seed_profile(home: Path, name: str, config: dict) -> Path:
    profile_dir = home if name == "default" else home / "profiles" / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return profile_dir


def test_get_profile_edit_reads_existing_config(nastech_home: Path) -> None:
    _seed_profile(nastech_home, "work", {"model": {"default": "m1"}, "toolsets": ["web"]})

    payload = get_profile_edit("work")
    assert payload["name"] == "work"
    assert payload["model"]["default"] == "m1"
    assert payload["toolsets"] == ["web"]


def test_update_round_trips_config_and_soul(nastech_home: Path) -> None:
    profile_dir = _seed_profile(
        nastech_home, "work", {"model": {"provider": "anthropic", "default": "claude-x"}}
    )

    body = ProfileEditBody(
        model=ProfileModelEdit(
            provider="anthropic", default="claude-opus", context_length=200000
        ),
        toolsets=["web", "file", "web"],  # duplicate is deduped
        skin="blade-runner",
        compression=ProfileCompressionEdit(
            enabled=True, summary_provider="anthropic", summary_model="haiku"
        ),
        soul="You are helpful.",
    )
    result = update_profile_edit("work", body)

    # response reflects the new state
    assert result["model"]["default"] == "claude-opus"
    assert result["model"]["context_length"] == 200000
    assert result["toolsets"] == ["web", "file"]
    assert result["skin"] == "blade-runner"
    assert result["compression"]["enabled"] is True
    assert result["soul"] == "You are helpful.\n"

    # config.yaml is valid YAML with the persisted values
    cfg = load_yaml((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["model"]["default"] == "claude-opus"
    assert cfg["toolsets"] == ["web", "file"]
    assert cfg["display"]["skin"] == "blade-runner"
    assert cfg["compression"]["enabled"] is True
    # SOUL.md written with a trailing newline
    assert (profile_dir / "SOUL.md").read_text(encoding="utf-8") == "You are helpful.\n"


def test_update_default_profile_writes_to_nastech_root(nastech_home: Path) -> None:
    _seed_profile(nastech_home, "default", {"model": {"default": "m"}})

    update_profile_edit(
        "default", ProfileEditBody(model=ProfileModelEdit(default="m2"), soul="hi")
    )

    cfg = load_yaml((nastech_home / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["model"]["default"] == "m2"
    assert (nastech_home / "SOUL.md").read_text(encoding="utf-8") == "hi\n"


def test_invalid_profile_name_is_rejected(nastech_home: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        get_profile_edit("../evil")
    assert exc.value.status_code == 400


def test_unknown_profile_returns_404(nastech_home: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        get_profile_edit("ghost")
    assert exc.value.status_code == 404


def test_cannot_clear_existing_model_default(nastech_home: Path) -> None:
    profile_dir = _seed_profile(
        nastech_home, "work", {"model": {"provider": "anthropic", "default": "claude-x"}}
    )

    body = ProfileEditBody(model=ProfileModelEdit(provider="anthropic", default=""))
    with pytest.raises(HTTPException) as exc:
        update_profile_edit("work", body)
    assert exc.value.status_code == 400

    # the original config must be untouched after a rejected edit
    cfg = load_yaml((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["model"]["default"] == "claude-x"


def test_base_url_must_be_http(nastech_home: Path) -> None:
    _seed_profile(nastech_home, "work", {"model": {"default": "m"}})

    body = ProfileEditBody(model=ProfileModelEdit(default="m", base_url="ftp://nope"))
    with pytest.raises(HTTPException) as exc:
        update_profile_edit("work", body)
    assert exc.value.status_code == 400


def test_update_leaves_no_temp_files(nastech_home: Path) -> None:
    profile_dir = _seed_profile(nastech_home, "work", {"model": {"default": "m"}})

    update_profile_edit(
        "work", ProfileEditBody(model=ProfileModelEdit(default="m2"), soul="hi")
    )

    leftovers = [p.name for p in profile_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_profile_edit_routes_are_registered(registered_routes) -> None:
    assert ("GET", "/api/profiles/{profile_name}/edit") in registered_routes
    assert ("PUT", "/api/profiles/{profile_name}/edit") in registered_routes
