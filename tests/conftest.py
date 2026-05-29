"""Shared pytest fixtures for Remy unit tests."""

import os

import pytest

# Set required env vars before any remy module is imported (config.py calls sys.exit otherwise).
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("VISION_MODEL", "qwen3-vl:2b")
os.environ.setdefault("CHEF_MODEL", "ministral-3:3b")
os.environ.setdefault("DB_PATH", "/tmp/remy-pytest.db")
os.environ.setdefault("RECENT_RECIPES_N", "3")


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Give each test its own SQLite file."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setattr("remy.config.DB_PATH", db_path)
