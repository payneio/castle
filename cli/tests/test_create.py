"""Tests for castle create command."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.config import load_config


class TestCreateCommand:
    """Tests for the create command."""

    def test_create_service(self, castle_root: Path, tmp_path: Path) -> None:
        """Create a new service project."""
        repos = tmp_path / "repos"
        with (
            patch("castle_cli.commands.create.load_config") as mock_load,
            patch("castle_cli.commands.create.save_config") as mock_save,
            patch("castle_cli.commands.create.REPOS_DIR", repos),
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="my-api",
                stack="python-fastapi",
                description="My API service",
                port=9050,
            )
            result = run_create(args)

        assert result == 0
        project_dir = repos / "my-api"
        assert project_dir.exists()
        assert (project_dir / "pyproject.toml").exists()
        assert (project_dir / "src" / "my_api" / "main.py").exists()
        assert (project_dir / "src" / "my_api" / "config.py").exists()
        assert (project_dir / "tests" / "conftest.py").exists()
        assert (project_dir / "tests" / "test_health.py").exists()
        assert (project_dir / "CLAUDE.md").exists()

        # Verify registered as ProgramSpec + ServiceSpec
        assert "my-api" in config.programs
        assert "my-api" in config.services
        svc = config.services["my-api"]
        assert svc.expose.http.internal.port == 9050
        assert svc.program == "my-api"
        mock_save.assert_called_once()

    def test_create_tool(self, castle_root: Path, tmp_path: Path) -> None:
        """Create a new tool project."""
        repos = tmp_path / "repos"
        with (
            patch("castle_cli.commands.create.load_config") as mock_load,
            patch("castle_cli.commands.create.save_config"),
            patch("castle_cli.commands.create.REPOS_DIR", repos),
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(name="my-tool2", stack="python-cli", description="My tool", port=None)
            result = run_create(args)

        assert result == 0
        project_dir = repos / "my-tool2"
        assert project_dir.exists()
        assert (project_dir / "src" / "my_tool2" / "main.py").exists()
        assert (project_dir / "CLAUDE.md").exists()
        assert "my-tool2" in config.programs
        comp = config.programs["my-tool2"]
        assert comp.kind == "tool"
        # A tool is a PATH deployment: manager=path.
        assert config.deployments["my-tool2"].manager == "path"

    def test_create_supabase_app(self, castle_root: Path, tmp_path: Path) -> None:
        """A supabase app scaffolds a Patch-shaped project registered as a static
        frontend (build.outputs=[public]) with no service."""
        repos = tmp_path / "repos"
        with (
            patch("castle_cli.commands.create.load_config") as mock_load,
            patch("castle_cli.commands.create.save_config"),
            patch("castle_cli.commands.create.REPOS_DIR", repos),
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="guestbook", stack="supabase", description="Guestbook", port=None
            )
            result = run_create(args)

        assert result == 0
        project_dir = repos / "guestbook"
        assert (project_dir / "migrations" / "0001_init.sql").exists()
        assert (project_dir / "functions" / "hello" / "index.ts").exists()
        assert (project_dir / "public" / "index.html").exists()
        assert (project_dir / "supabase.app.yaml").exists()

        # Registered as a program + a caddy (static) deployment serving public/
        comp = config.programs["guestbook"]
        assert comp.kind == "static"
        assert comp.stack == "supabase"
        assert comp.build is not None and comp.build.outputs == ["public"]
        dep = config.deployments["guestbook"]
        assert dep.manager == "caddy"
        assert dep.root == "public"

    def test_create_duplicate_fails(self, castle_root: Path, capsys: object) -> None:
        """Creating a project with existing name fails."""
        with patch("castle_cli.commands.create.load_config") as mock_load:
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            # test-svc exists in the services section
            args = Namespace(
                name="test-svc",
                stack="python-fastapi",
                description="Duplicate",
                port=None,
            )
            result = run_create(args)

        assert result == 1

    def test_create_auto_port(self, castle_root: Path, tmp_path: Path) -> None:
        """Service creation auto-assigns next available port."""
        with (
            patch("castle_cli.commands.create.load_config") as mock_load,
            patch("castle_cli.commands.create.save_config"),
            patch("castle_cli.commands.create.REPOS_DIR", tmp_path / "repos"),
        ):
            config = load_config(castle_root)
            mock_load.return_value = config

            from castle_cli.commands.create import run_create

            args = Namespace(
                name="auto-port-svc",
                stack="python-fastapi",
                description="Auto port",
                port=None,
            )
            run_create(args)

        svc = config.services["auto-port-svc"]
        port = svc.expose.http.internal.port
        # Port 18000 is gateway, 19000 is test-svc, so next should be 9001+
        assert port is not None
        assert port not in (18000, 19000)
