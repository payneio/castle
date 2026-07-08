"""Derive LLM tool-call schemas from a CLI tool's ``--help``.

castle's in-process version of the standalone ``toolify`` tool: given a tool (a
program with a ``path`` deployment), resolve its executable, run ``--help``, and
build a tool-call definition.

Two parameter shapes, chosen automatically:

* **structured** — one typed property per option/positional, parsed from a
  standard argparse/click ``--help``, each carrying an ``x-cli`` executor hint.
  Used when the help is recognizable *and* the tool has no subcommands.
* **command** — a single ``command`` string, full ``--help`` as description. The
  universal fallback for non-standard help (``jq``) and subcommand trees.

Schemas are built and stored in a **neutral** core (``{name, description,
parameters}``); ``render_tool_schema`` wraps that in the Anthropic or OpenAI
envelope on read. castle's feed defaults to OpenAI (litellm-native).

The extraction is intentionally duplicated from ``toolify`` rather than shared —
``toolify`` is a standalone program that must never depend on castle. No LLM is
used; the output is a deterministic function of the tool's ``--help``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from castle_core.config import CastleConfig

__all__ = [
    "ToolSchemaError",
    "derive_tool_schema",
    "render_tool_schema",
    "tool_executable",
]

_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")
_HELP_TIMEOUT = 10
_MAX_SUBCOMMANDS = 40
_SKIP_OPTS = {"help", "version"}
_CMD_HEADING = re.compile(
    r"^\s*(commands|subcommands|available commands)\s*:?\s*$", re.IGNORECASE
)
_OPT_HEADING = re.compile(r"^\s*(options|optional arguments)\s*:?\s*$", re.IGNORECASE)
_POS_HEADING = re.compile(r"^\s*positional arguments\s*:?\s*$", re.IGNORECASE)


class ToolSchemaError(Exception):
    """The tool's executable couldn't be resolved or produced no help."""


def _sanitize_name(raw: str) -> str:
    name = _NAME_OK.sub("_", raw).strip("_") or "tool"
    return name[:64]


def _run_help(argv: list[str]) -> tuple[int | None, str]:
    """Run ``argv + ['--help']`` → ``(returncode, help_text)``; never raises."""
    for flag in ("--help", "-h"):
        try:
            proc = subprocess.run(
                [*argv, flag],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=_HELP_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        text = proc.stdout.strip() or proc.stderr.strip()
        if text:
            return proc.returncode, text
    return None, ""


def _section_entries(help_text: str, heading_re: re.Pattern[str]) -> list[list[str]]:
    """Entries (each a list of lines) under headings matching ``heading_re``. A
    row at the section's minimum indent starts an entry; deeper rows continue it."""
    out: list[list[str]] = []
    lines = help_text.splitlines()
    i = 0
    while i < len(lines):
        if not heading_re.match(lines[i]):
            i += 1
            continue
        i += 1
        body: list[str] = []
        while i < len(lines) and (not lines[i].strip() or lines[i][:1].isspace()):
            if lines[i].strip():
                body.append(lines[i])
            i += 1
        if not body:
            continue
        term = min(len(ln) - len(ln.lstrip()) for ln in body)
        cur: list[str] = []
        for ln in body:
            if (len(ln) - len(ln.lstrip())) == term:
                if cur:
                    out.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            out.append(cur)
    return out


def _extract_subcommands(help_text: str) -> list[str]:
    """Subcommand names, or [] for a flat tool. Only click ``Commands:`` entries
    and argparse ``{a,b,c}`` choice rows count — a plain positional does not."""
    cmds: list[str] = []
    for entry in _section_entries(help_text, _CMD_HEADING):
        word = re.match(r"^([A-Za-z][\w-]*)\b", entry[0].strip())
        if word:
            cmds.append(word.group(1))
    for entry in _section_entries(help_text, _POS_HEADING):
        choice = re.match(r"^\{([^}]+)\}", entry[0].strip())
        if choice:
            cmds.extend(p.strip() for p in choice.group(1).split(","))
    seen: list[str] = []
    for c in cmds:
        if c and c not in seen:
            seen.append(c)
    return seen


def _entry_head_and_desc(entry: list[str]) -> tuple[str, str]:
    m = re.match(r"^\s*(.*?)(?:\s{2,}(.*))?$", entry[0])
    head = (m.group(1) if m else entry[0]).strip()
    desc_parts = [m.group(2)] if m and m.group(2) else []
    desc_parts += [ln.strip() for ln in entry[1:]]
    return head, " ".join(p for p in desc_parts if p).strip()


def _parse_option(entry: list[str]) -> tuple[str, dict] | None:
    head, desc = _entry_head_and_desc(entry)
    flags: list[str] = []
    metavar: str | None = None
    for tok in head.split(", "):
        fm = re.match(r"^(-{1,2}[\w-]+)(?:[ =](.+))?$", tok.strip())
        if not fm:
            continue
        flags.append(fm.group(1))
        if fm.group(2):
            metavar = fm.group(2).strip()
    longs = [f for f in flags if f.startswith("--")]
    canonical = longs[-1] if longs else (flags[0] if flags else None)
    if not canonical:
        return None
    key = canonical.lstrip("-").replace("-", "_")
    if key in _SKIP_OPTS:
        return None
    prop: dict = {}
    if metavar and metavar.startswith("{") and metavar.endswith("}"):
        prop["type"] = "string"
        prop["enum"] = [v.strip() for v in metavar[1:-1].split(",")]
    elif metavar:
        prop["type"] = "string"
    else:
        prop["type"] = "boolean"
    if desc:
        prop["description"] = desc
    prop["x-cli"] = {"flag": canonical, "value": bool(metavar)}
    return key, prop


def _parse_positional(entry: list[str], order: int) -> tuple[str, dict] | None:
    head, desc = _entry_head_and_desc(entry)
    if head.startswith("{"):
        return None
    nm = re.match(r"^([A-Za-z][\w-]*)", head)
    if not nm:
        return None
    key = nm.group(1).replace("-", "_")
    prop: dict = {"type": "string"}
    if desc:
        prop["description"] = desc
    prop["x-cli"] = {"positional": True, "order": order}
    return key, prop


def _summary(help_text: str, fallback: str) -> str:
    for para in re.split(r"\n\s*\n", help_text):
        p = para.strip()
        if not p or p.lower().startswith("usage:") or p.rstrip().endswith(":"):
            continue
        return " ".join(p.split())
    return fallback


def _structured_core(name: str, help_text: str) -> dict | None:
    props: dict = {}
    required: list[str] = []
    for order, entry in enumerate(_section_entries(help_text, _POS_HEADING)):
        parsed = _parse_positional(entry, order)
        if parsed:
            key, prop = parsed
            props[key] = prop
            required.append(key)
    for entry in _section_entries(help_text, _OPT_HEADING):
        parsed = _parse_option(entry)
        if parsed:
            key, prop = parsed
            props[key] = prop
    if not props:
        return None
    parameters: dict = {"type": "object", "properties": props}
    if required:
        parameters["required"] = required
    return {
        "name": _sanitize_name(name),
        "description": _summary(help_text, f"Run the `{name}` command-line tool."),
        "parameters": parameters,
    }


def _command_core(name: str, argv: list[str], help_text: str, deep: bool) -> dict:
    parts = [
        f"Run the `{name}` command-line tool. Provide the arguments in the "
        f"`command` parameter; the executable name is prepended automatically. "
        f"Below is the tool's help output.",
        f"\n$ {name} --help\n{help_text}",
    ]
    if deep:
        for sub in _extract_subcommands(help_text)[:_MAX_SUBCOMMANDS]:
            rc, sub_help = _run_help([*argv, sub])
            if rc == 0 and sub_help:
                parts.append(f"\n$ {name} {sub} --help\n{sub_help}")
    return {
        "name": _sanitize_name(name),
        "description": "\n".join(parts),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        f"Arguments to pass to `{name}`. The full command line run "
                        f"is `{name} ` followed by this string. Do not include the "
                        f"leading `{name}`."
                    ),
                }
            },
            "required": ["command"],
        },
    }


def tool_executable(config: CastleConfig, name: str) -> str:
    """The console script to invoke for tool ``name`` — its first
    ``[project.scripts]`` key (source of truth even when uninstalled), else the
    program name. Mirrors the CLI's tools lens."""
    comp = config.programs.get(name)
    src = getattr(comp, "source", None) if comp else None
    if src:
        pyproject = Path(src) / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                scripts = data.get("project", {}).get("scripts", {})
                if scripts:
                    return sorted(scripts.keys())[0]
            except (OSError, tomllib.TOMLDecodeError):
                pass
    return name


def collect_tool_help(config: CastleConfig, name: str) -> str:
    """The full recursive ``--help`` text for tool ``name`` — top-level plus each
    subcommand's help, the raw material an LLM assist reads to structure a
    subcommand tree. Deterministic; raises ``ToolSchemaError`` if unresolved.
    """
    exe_name = tool_executable(config, name)
    exe = shutil.which(exe_name)
    if exe is None:
        raise ToolSchemaError(
            f"`{exe_name}` is not on PATH — install the tool (enable it, then "
            f"`castle apply`) before generating its schema."
        )
    _, help_text = _run_help([exe])
    if not help_text:
        raise ToolSchemaError(f"`{exe_name} --help` produced no output.")
    parts = [f"$ {exe_name} --help\n{help_text}"]
    for sub in _extract_subcommands(help_text)[:_MAX_SUBCOMMANDS]:
        rc, sub_help = _run_help([exe, sub])
        if rc == 0 and sub_help:
            parts.append(f"\n$ {exe_name} {sub} --help\n{sub_help}")
    return "\n".join(parts)


def validate_tool_schema_core(core: object) -> list[str]:
    """Deterministically validate a neutral tool-call core.

    Returns a list of human-readable error strings (empty ⇒ valid). Checks the
    ``{name, description, parameters}`` shape *and* that ``parameters`` is a valid
    JSON Schema (via ``jsonschema`` meta-validation, which catches malformed
    properties like an ``enum`` that isn't a list — the defect weak models hit).
    Shared by the LLM repair loop, the ``validate`` endpoint, and the accept gate.
    """
    errors: list[str] = []
    if not isinstance(core, dict):
        return ["schema must be a JSON object"]
    name = core.get("name")
    if not isinstance(name, str) or not name:
        errors.append("`name` must be a non-empty string")
    elif not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
        errors.append("`name` must match ^[a-zA-Z0-9_-]{1,64}$")
    if not isinstance(core.get("description"), str):
        errors.append("`description` must be a string")

    params = core.get("parameters")
    if not isinstance(params, dict):
        errors.append("`parameters` must be an object")
        return errors
    if params.get("type") != "object":
        errors.append('`parameters.type` must be "object"')
    props = params.get("properties")
    if not isinstance(props, dict):
        errors.append("`parameters.properties` must be an object")
    elif not props:
        errors.append("`parameters.properties` is empty — no arguments captured")

    try:
        import jsonschema
        from jsonschema.exceptions import SchemaError

        try:
            jsonschema.Draft202012Validator.check_schema(params)
        except SchemaError as e:
            loc = "/".join(str(p) for p in e.absolute_path) or "parameters"
            errors.append(f"invalid JSON Schema at `{loc}`: {e.message}")
    except ImportError:  # jsonschema not installed — structural checks stand alone
        pass
    return errors


def is_tool_schema_core(obj: object) -> bool:
    """True if ``obj`` is a valid neutral tool-call core (no validation errors)."""
    return not validate_tool_schema_core(obj)


def derive_tool_schema(config: CastleConfig, name: str, deep: bool = False) -> dict:
    """Derive the neutral tool-call core for tool ``name`` from its ``--help``.

    Structured params when the help is standard and flat; the command-string
    fallback for non-standard help / subcommand trees. Raises ``ToolSchemaError``
    if the executable isn't on PATH or emits no help.
    """
    exe_name = tool_executable(config, name)
    exe = shutil.which(exe_name)
    if exe is None:
        raise ToolSchemaError(
            f"`{exe_name}` is not on PATH — install the tool (enable it, then "
            f"`castle apply`) before generating its schema."
        )
    _, help_text = _run_help([exe])
    if not help_text:
        raise ToolSchemaError(f"`{exe_name} --help` produced no output.")
    if not _extract_subcommands(help_text):
        structured = _structured_core(exe_name, help_text)
        if structured:
            return structured
    return _command_core(exe_name, [exe], help_text, deep)


def render_tool_schema(core: dict, fmt: str = "openai") -> dict:
    """Wrap a neutral core in a provider envelope.

    ``openai`` (default, litellm-native) → ``{type: function, function: {…}}``;
    ``anthropic`` → ``{name, description, input_schema}``; ``neutral`` → as stored.
    """
    if fmt == "neutral":
        return core
    if fmt == "anthropic":
        return {
            "name": core["name"],
            "description": core["description"],
            "input_schema": core["parameters"],
        }
    return {
        "type": "function",
        "function": {
            "name": core["name"],
            "description": core["description"],
            "parameters": core["parameters"],
        },
    }
