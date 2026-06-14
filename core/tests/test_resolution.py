"""Tests for per-program verb resolution (declared commands → stack → none)."""

from __future__ import annotations

from castle_core.manifest import ProgramSpec
from castle_core.stacks import _declared_commands, available_actions, is_available


class TestResolution:
    def test_stack_only_program_unchanged(self) -> None:
        """A program with a stack and no commands resolves all stack verbs."""
        p = ProgramSpec.model_validate({"source": "/tmp/x", "stack": "python-cli"})
        actions = available_actions(p)
        assert "build" in actions and "test" in actions and "lint" in actions
        assert "install" in actions and "uninstall" in actions
        # `run` is declared-only — a bare stack program does not expose it.
        assert "run" not in actions

    def test_wired_in_program_no_stack(self) -> None:
        """A program with no stack but declared commands resolves those verbs."""
        p = ProgramSpec.model_validate(
            {
                "source": "/tmp/y",
                "commands": {"lint": [["make", "lint"]], "test": [["make", "test"]], "run": [["./bin/y"]]},
            }
        )
        actions = available_actions(p)
        assert set(actions) >= {"lint", "test", "run"}
        assert "build" not in actions  # not declared, no stack
        assert _declared_commands(p, "lint") == [["make", "lint"]]

    def test_check_available_when_subverbs_are(self) -> None:
        """`check` is a composite; available when any of lint/type-check/test is."""
        p = ProgramSpec.model_validate(
            {"source": "/tmp/y", "commands": {"lint": [["ruff", "check", "."]]}}
        )
        assert is_available(p, "check")

    def test_hybrid_override_one_verb(self) -> None:
        """A stack program can override a single verb; the rest fall back to stack."""
        p = ProgramSpec.model_validate(
            {"source": "/tmp/z", "stack": "python-cli", "commands": {"test": [["pytest", "-x"]]}}
        )
        assert _declared_commands(p, "test") == [["pytest", "-x"]]
        assert _declared_commands(p, "build") is None  # build still comes from the stack

    def test_build_declared_via_buildspec(self) -> None:
        """`build` is declared through BuildSpec.commands, not CommandsSpec."""
        p = ProgramSpec.model_validate(
            {"source": "/tmp/w", "build": {"commands": [["make"]], "outputs": ["dist/"]}}
        )
        assert _declared_commands(p, "build") == [["make"]]
        assert "build" in available_actions(p)

    def test_no_source_no_actions(self) -> None:
        p = ProgramSpec.model_validate({"description": "a library"})
        assert available_actions(p) == []
