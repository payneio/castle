"""Tests for castle create command."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.config import load_config
from castle_cli.manifest import Role


class TestCreateCommand:
    """Tests for the create command."""

    def test_create_service(self, castle_root: Path) -> None:
        """Create a new service project."""
        with patch("castle_cli.commands.create.load_config") as mock_load, patch(
            "castle_cli.commands.create.save_config"
        ) as mock_save:
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="my-api",
                type="service",
                description="My API service",
                port=9050,
            )
            result = run_create(args)

        assert result == 0
        project_dir = castle_root / "my-api"
        assert project_dir.exists()
        assert (project_dir / "pyproject.toml").exists()
        assert (project_dir / "src" / "my_api" / "main.py").exists()
        assert (project_dir / "src" / "my_api" / "config.py").exists()
        assert (project_dir / "tests" / "conftest.py").exists()
        assert (project_dir / "tests" / "test_health.py").exists()
        assert (project_dir / "CLAUDE.md").exists()

        # Verify registered as ComponentManifest
        assert "my-api" in config.components
        manifest = config.components["my-api"]
        assert Role.SERVICE in manifest.roles
        assert manifest.expose.http.internal.port == 9050
        mock_save.assert_called_once()

    def test_create_tool(self, castle_root: Path) -> None:
        """Create a new tool project."""
        with patch("castle_cli.commands.create.load_config") as mock_load, patch(
            "castle_cli.commands.create.save_config"
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="my-tool", type="tool", description="My tool", port=None
            )
            result = run_create(args)

        assert result == 0
        project_dir = castle_root / "my-tool"
        assert project_dir.exists()
        assert (project_dir / "src" / "my_tool" / "main.py").exists()
        assert (project_dir / "CLAUDE.md").exists()
        assert "my-tool" in config.components
        manifest = config.components["my-tool"]
        assert Role.TOOL in manifest.roles

    def test_create_library(self, castle_root: Path) -> None:
        """Create a new library project."""
        with patch("castle_cli.commands.create.load_config") as mock_load, patch(
            "castle_cli.commands.create.save_config"
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="my-lib", type="library", description="My library", port=None
            )
            result = run_create(args)

        assert result == 0
        project_dir = castle_root / "my-lib"
        assert project_dir.exists()
        assert (project_dir / "src" / "my_lib" / "__init__.py").exists()
        assert (project_dir / "CLAUDE.md").exists()
        assert "my-lib" in config.components

    def test_create_duplicate_fails(self, castle_root: Path, capsys: object) -> None:
        """Creating a project with existing name fails."""
        with patch("castle_cli.commands.create.load_config") as mock_load:
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="test-svc",
                type="service",
                description="Duplicate",
                port=None,
            )
            result = run_create(args)

        assert result == 1

    def test_create_auto_port(self, castle_root: Path) -> None:
        """Service creation auto-assigns next available port."""
        with patch("castle_cli.commands.create.load_config") as mock_load, patch(
            "castle_cli.commands.create.save_config"
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="auto-port-svc",
                type="service",
                description="Auto port",
                port=None,
            )
            run_create(args)

        manifest = config.components["auto-port-svc"]
        port = manifest.expose.http.internal.port
        # Port 18000 is gateway, 19000 is test-svc, so next should be 9001+
        assert port is not None
        assert port not in (18000, 19000)
