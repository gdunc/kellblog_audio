from __future__ import annotations

import importlib


def _reload_config(monkeypatch, *, github_actions: str | None, cfg_weight: str | None):
    if github_actions is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    if cfg_weight is None:
        monkeypatch.delenv("KELLBLOG_CHATTERBOX_CFG_WEIGHT", raising=False)
    else:
        monkeypatch.setenv("KELLBLOG_CHATTERBOX_CFG_WEIGHT", cfg_weight)

    import kellblog_audio.config as config

    return importlib.reload(config)


def test_chatterbox_cfg_weight_defaults_to_standard_locally(monkeypatch):
    config = _reload_config(monkeypatch, github_actions=None, cfg_weight=None)

    assert config.CHATTERBOX_CFG_WEIGHT == 0.5


def test_chatterbox_cfg_weight_uses_lighter_github_actions_default(monkeypatch):
    config = _reload_config(monkeypatch, github_actions="true", cfg_weight=None)

    assert config.CHATTERBOX_CFG_WEIGHT == 0.35


def test_chatterbox_cfg_weight_env_override_wins(monkeypatch):
    config = _reload_config(monkeypatch, github_actions="true", cfg_weight="0.42")

    assert config.CHATTERBOX_CFG_WEIGHT == 0.42
