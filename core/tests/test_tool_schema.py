"""Tests for castle_core.tool_schema — deriving neutral tool-call cores from --help."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from castle_core.tool_schema import (
    ToolSchemaError,
    _command_core,
    _extract_subcommands,
    _sanitize_name,
    _structured_core,
    collect_tool_help,
    derive_tool_schema,
    is_tool_schema_core,
    render_tool_schema,
    tool_executable,
    validate_tool_schema_core,
)

FLAT_HELP = """\
usage: widget [-h] [--deep] [--mode {a,b}] target

Do a widget thing.

positional arguments:
  target                What to widget

options:
  -h, --help            show this help message and exit
  --deep                Recurse
  --mode {a,b}          Pick a mode
"""

SUBCMD_HELP = "positional arguments:\n  {build,deploy}\n    build   Build\n"


def _fake_config(programs: dict) -> object:
    return SimpleNamespace(programs=programs)


class TestPure:
    def test_sanitize_name(self) -> None:
        assert _sanitize_name("my.tool v2") == "my_tool_v2"
        assert len(_sanitize_name("x" * 100)) == 64

    def test_flat_tool_has_no_subcommands(self) -> None:
        assert _extract_subcommands(FLAT_HELP) == []

    def test_argparse_choice_row_subcommands(self) -> None:
        assert _extract_subcommands(SUBCMD_HELP) == ["build", "deploy"]

    def test_structured_core_typed_params(self) -> None:
        core = _structured_core("widget", FLAT_HELP)
        assert core is not None
        props = core["parameters"]["properties"]
        assert set(props) == {"target", "deep", "mode"}
        assert props["deep"]["type"] == "boolean"
        assert props["mode"]["enum"] == ["a", "b"]
        assert core["parameters"]["required"] == ["target"]

    def test_structured_none_without_options(self) -> None:
        assert _structured_core("x", "free-form help\n") is None

    def test_command_core_shape(self) -> None:
        core = _command_core("jq", ["/usr/bin/jq"], "Usage: jq ...", deep=False)
        assert core["parameters"]["required"] == ["command"]


class TestRender:
    def test_render_openai_default(self) -> None:
        core = _command_core("jq", ["/usr/bin/jq"], "help", deep=False)
        out = render_tool_schema(core)
        assert out["type"] == "function"
        assert out["function"]["parameters"] == core["parameters"]

    def test_render_anthropic(self) -> None:
        core = _command_core("jq", ["/usr/bin/jq"], "help", deep=False)
        out = render_tool_schema(core, "anthropic")
        assert set(out) == {"name", "description", "input_schema"}
        assert out["input_schema"] == core["parameters"]

    def test_render_neutral_is_identity(self) -> None:
        core = _command_core("jq", ["/usr/bin/jq"], "help", deep=False)
        assert render_tool_schema(core, "neutral") is core


class TestResolution:
    def test_tool_executable_falls_back_to_name(self) -> None:
        cfg = _fake_config({"widget": SimpleNamespace(source=None)})
        assert tool_executable(cfg, "widget") == "widget"

    def test_tool_executable_reads_pyproject_scripts(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\nintent-router = "x:main"\n'
        )
        cfg = _fake_config({"r": SimpleNamespace(source=str(tmp_path))})
        assert tool_executable(cfg, "r") == "intent-router"


class TestDerive:
    def test_missing_executable_raises(self) -> None:
        cfg = _fake_config({"nope": SimpleNamespace(source=None)})
        with pytest.raises(ToolSchemaError, match="not on PATH"):
            derive_tool_schema(cfg, "nope")

    def test_derive_real_tool_returns_neutral_core(self) -> None:
        cfg = _fake_config({"python3": SimpleNamespace(source=None)})
        core = derive_tool_schema(cfg, "python3")
        assert core["name"] == "python3"
        assert "parameters" in core  # neutral shape, not input_schema
        assert core["description"]


class TestLLMAssistHelpers:
    """Deterministic helpers that feed / validate the (castle-api) LLM assist."""

    def test_collect_tool_help_real_tool(self) -> None:
        cfg = _fake_config({"python3": SimpleNamespace(source=None)})
        help_text = collect_tool_help(cfg, "python3")
        assert help_text and "$ python3 --help" in help_text

    def test_collect_tool_help_missing_raises(self) -> None:
        cfg = _fake_config({"nope": SimpleNamespace(source=None)})
        with pytest.raises(ToolSchemaError, match="not on PATH"):
            collect_tool_help(cfg, "nope")

    def test_is_tool_schema_core(self) -> None:
        good = {
            "name": "jq",
            "description": "process json",
            "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}},
        }
        assert is_tool_schema_core(good) is True
        assert is_tool_schema_core({"name": "x", "description": "y"}) is False  # no params
        assert is_tool_schema_core("nope") is False


class TestValidate:
    """Deterministic validation — shape + JSON-Schema meta-validation."""

    _GOOD = {
        "name": "jq",
        "description": "process json",
        "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}},
    }

    def test_valid_returns_no_errors(self) -> None:
        assert validate_tool_schema_core(self._GOOD) == []

    def test_malformed_enum_is_caught(self) -> None:
        """The qwen defect: `enum` as a count, not a list — a JSON-Schema error."""
        bad = {
            "name": "search",
            "description": "d",
            "parameters": {
                "type": "object",
                "properties": {"sub": {"type": "string", "enum": 4}},
            },
        }
        errors = validate_tool_schema_core(bad)
        assert errors and any("JSON Schema" in e for e in errors)

    def test_missing_parameters(self) -> None:
        assert validate_tool_schema_core({"name": "x", "description": "y"})

    def test_empty_properties(self) -> None:
        errors = validate_tool_schema_core(
            {"name": "x", "description": "y", "parameters": {"type": "object", "properties": {}}}
        )
        assert any("empty" in e for e in errors)

    def test_bad_name_char(self) -> None:
        errors = validate_tool_schema_core(
            {**self._GOOD, "name": "has space"}
        )
        assert any("name" in e for e in errors)

    def test_parameters_not_object_type(self) -> None:
        errors = validate_tool_schema_core(
            {"name": "x", "description": "y", "parameters": {"type": "array", "properties": {}}}
        )
        assert errors
