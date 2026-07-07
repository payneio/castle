"""Tests for the castle mesh command (API calls mocked)."""

from __future__ import annotations

import urllib.error
from argparse import Namespace
from unittest.mock import patch

from castle_cli.commands.mesh import run_mesh


class TestMeshCommand:
    def test_status(self, capsys: object) -> None:
        data = {
            "enabled": True, "connected": True, "nats_url": "tls://x:4222",
            "peer_count": 1, "peers": ["primer"],
        }
        with patch("castle_cli.commands.mesh._get", return_value=data):
            rc = run_mesh(Namespace(mesh_command="status"))
        assert rc == 0
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "connected" in out and "primer" in out

    def test_nodes(self, capsys: object) -> None:
        data = [
            {"hostname": "civil", "online": True, "is_stale": False,
             "deployed_count": 5, "is_local": True},
            {"hostname": "primer", "online": True, "is_stale": False,
             "deployed_count": 3, "is_local": False},
        ]
        with patch("castle_cli.commands.mesh._get", return_value=data):
            rc = run_mesh(Namespace(mesh_command="nodes"))
        assert rc == 0
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "civil" in out and "primer" in out

    def test_config_list(self, capsys: object) -> None:
        data = {"role": "authority", "keys": ["fleet/motd"]}
        with patch("castle_cli.commands.mesh._get", return_value=data):
            rc = run_mesh(
                Namespace(mesh_command="config", mesh_config_command="list")
            )
        assert rc == 0
        assert "fleet/motd" in capsys.readouterr().out  # type: ignore[attr-defined]

    def test_config_set_calls_put(self) -> None:
        with patch(
            "castle_cli.commands.mesh._put", return_value={"ok": True}
        ) as put:
            rc = run_mesh(
                Namespace(
                    mesh_command="config",
                    mesh_config_command="set",
                    key="fleet/x",
                    value="v",
                )
            )
        assert rc == 0
        put.assert_called_once()

    def test_api_unreachable_returns_1(self, capsys: object) -> None:
        with patch(
            "castle_cli.commands.mesh._get",
            side_effect=urllib.error.URLError("refused"),
        ):
            rc = run_mesh(Namespace(mesh_command="status"))
        assert rc == 1
