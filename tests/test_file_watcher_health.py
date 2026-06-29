from pathlib import Path

from backend.file_watcher import _detect_change_type


def test_health_relevant_files_emit_health_data_type() -> None:
    cases = [
        Path("/home/me/.nastech/.env"),
        Path("/home/me/.nastech/config.yaml"),
        Path("/home/me/.nastech/logs/gateway.log"),
        Path("/home/me/.nastech/models_dev_cache.json"),
        Path("/home/me/.nastech/plugins/example/plugin.json"),
    ]

    for path in cases:
        assert "health" in _detect_change_type(path)


def test_health_relevant_files_keep_feature_specific_types() -> None:
    assert "profiles" in _detect_change_type(Path("/home/me/.nastech/config.yaml"))
    assert "gateway" in _detect_change_type(Path("/home/me/.nastech/logs/gateway.log"))
    assert "plugins" in _detect_change_type(Path("/home/me/.nastech/plugins/example/plugin.json"))
    assert "model-info" in _detect_change_type(Path("/home/me/.nastech/models_dev_cache.json"))
