"""Vault store must not fall back to Emma catalog for other accounts."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


def test_validate_map_for_account_mismatch():
    from db.vault_store import validate_map_for_account

    assert validate_map_for_account({"account_id": "emma"}, "sophia")


def test_load_items_pg_empty_no_file_fallback(monkeypatch):
    monkeypatch.setenv("ACCOUNT_ID", "sophia")
    monkeypatch.delenv("FANVUE_MEDIA_MAP", raising=False)

    with patch("db.vault_store.use_postgres", return_value=True):
        with patch("db.pg.session_scope") as sc:
            ctx = MagicMock()
            sc.return_value.__enter__ = MagicMock(return_value=ctx)
            sc.return_value.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.mappings.return_value.all.return_value = []

            with patch("db.vault_store._items_from_file") as file_load:
                from db.vault_store import load_items

                assert load_items() == []
                file_load.assert_not_called()


def test_default_map_path_prefers_per_account(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCOUNT_ID", "sophia")
    monkeypatch.delenv("FANVUE_MEDIA_MAP", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "fanvue_media_map.json").write_text('{"account_id":"emma","items":[]}')
    (data_dir / "sophia_fanvue_media_map.json").write_text(
        '{"account_id":"sophia","items":[]}'
    )

    with patch("db.vault_store._ROOT", tmp_path):
        from db.vault_store import _default_map_path

        p = _default_map_path("sophia")
        assert p.name == "sophia_fanvue_media_map.json"
