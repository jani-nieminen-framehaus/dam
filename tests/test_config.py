"""Tests for dam_config module."""

import json
from pathlib import Path


def test_defaults_without_config_file(tmp_path, monkeypatch):
    """Config loads with all defaults when no config file exists."""
    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", tmp_path / "nonexistent" / "config.json")
    cfg = dam_config._load_config()

    assert cfg["port"] == 5001
    assert cfg["thumb_workers"] == 8
    assert cfg["burst_gap_seconds"] == 2.0
    assert cfg["embed_dim"] == 768
    assert cfg["ollama_base"] == "http://localhost:11434"
    assert isinstance(cfg["dam_root"], Path)
    assert isinstance(cfg["db_path"], Path)


def test_override_single_value(tmp_path, monkeypatch):
    """User config overrides specific values, rest stay default."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"port": 9000, "thumb_workers": 4}))

    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", config_file)
    cfg = dam_config._load_config()

    assert cfg["port"] == 9000
    assert cfg["thumb_workers"] == 4
    # Other values still defaults
    assert cfg["burst_gap_seconds"] == 2.0
    assert cfg["page_size"] == 50


def test_derived_paths(tmp_path, monkeypatch):
    """db_path and thumb_dir derive from dam_root when null."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"dam_root": str(tmp_path / "my_dam")}))

    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", config_file)
    cfg = dam_config._load_config()

    assert cfg["db_path"] == tmp_path / "my_dam" / "dam.db"
    assert cfg["thumb_dir"] == tmp_path / "my_dam" / "thumbs"


def test_explicit_db_path_override(tmp_path, monkeypatch):
    """Explicit db_path in config is not overridden by derivation."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "dam_root": str(tmp_path / "my_dam"),
                "db_path": str(tmp_path / "custom.db"),
            }
        )
    )

    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", config_file)
    cfg = dam_config._load_config()

    assert cfg["db_path"] == tmp_path / "custom.db"


def test_auto_create_config(tmp_path, monkeypatch):
    """Config dir and file are auto-created on first run."""
    new_dir = tmp_path / "new_config_dir"
    config_file = new_dir / "config.json"

    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_DIR", new_dir)
    monkeypatch.setattr(dam_config, "CONFIG_FILE", config_file)
    dam_config._load_config()

    assert new_dir.exists()
    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert "port" in data
    assert "ollama_base" in data


def test_frozen_does_not_override_dam_root(tmp_path, monkeypatch):
    """When frozen (PyInstaller), dam_root stays as ~/Documents/dam, not exe dir."""
    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", tmp_path / "nonexistent" / "config.json")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", "/Applications/DAM.app/Contents/MacOS/dam")
    cfg = dam_config._load_config()

    # dam_root should be the default ~/Documents/dam, NOT /Applications/DAM.app/Contents/MacOS/
    assert "Applications" not in str(cfg["dam_root"])
    assert cfg["dam_root"] == Path.home() / "Documents" / "dam"


def test_ignore_volumes_is_set(tmp_path, monkeypatch):
    """ignore_volumes is converted to a set."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({}))

    import dam_config

    monkeypatch.setattr(dam_config, "CONFIG_FILE", config_file)
    cfg = dam_config._load_config()

    assert isinstance(cfg["ignore_volumes"], set)
    assert "Macintosh HD" in cfg["ignore_volumes"]
