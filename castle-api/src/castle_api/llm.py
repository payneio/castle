"""LLM assist — generate a tool-call schema from a CLI's --help via the litellm proxy.

castle's first LLM-backed feature. The deterministic parser
(``castle_core.tool_schema``) falls back to a single ``command`` string for
subcommand trees (git, castle); this asks an LLM to read the recursive ``--help``
and produce a *structured* neutral tool-call core instead.

Goes through castle's litellm proxy over its OpenAI-compatible
``/chat/completions`` (model-agnostic; the fleet standardizes on litellm), using
forced tool-calling to constrain the output. Every response is validated
deterministically (``validate_tool_schema_core``); on failure the errors are fed
back to the model to repair, up to a cap — so a weak model's malformed draft is
fixed rather than surfaced. The result is a reviewed draft — never auto-saved.
"""

from __future__ import annotations

import json

import httpx

from castle_core.config import read_secret
from castle_core.tool_schema import validate_tool_schema_core

from castle_api.config import settings

_TIMEOUT = 60.0
# Total attempts = 1 initial + repairs. Sonnet is valid first try; the extra
# rounds salvage weaker models (repairing a bad enum, etc.).
_MAX_ATTEMPTS = 3
_SYSTEM = (
    "You convert a command-line tool's --help output into a tool-call schema for "
    "an AI agent. Call the `emit_tool_schema` function exactly once. Produce a "
    "JSON Schema in `parameters` (type: object) whose properties let an agent "
    "invoke the tool: one property per meaningful option or subcommand path, each "
    "typed (boolean for flags, string for valued options, enum as a LIST of the "
    "allowed values for fixed choices) with a concise description drawn from the "
    "help. For a tool with subcommands, include a `subcommand` property (an enum "
    "listing the available subcommands) plus the important shared options. `name` "
    "must match ^[a-zA-Z0-9_-]{1,64}$. Do not invent options not in the help."
)

_EMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_tool_schema",
        "description": "Emit the structured tool-call definition for this CLI.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Sanitized tool name."},
                "description": {
                    "type": "string",
                    "description": "One-line description of what the tool does.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "A JSON Schema object (type: object with a properties map) "
                        "describing the tool's invocation arguments."
                    ),
                },
            },
            "required": ["name", "description", "parameters"],
        },
    },
}


class LLMAssistError(Exception):
    """The LLM assist couldn't produce a valid schema (config, upstream, or output)."""


def _extract_args(data: dict) -> dict | None:
    """Pull the emit_tool_schema arguments out of a chat-completions response.

    Returns the parsed arguments dict (even if not yet valid — the caller
    validates), or None if the model didn't call the function / returned non-JSON.
    """
    try:
        call = data["choices"][0]["message"]["tool_calls"][0]
        args = call["function"]["arguments"]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    return args if isinstance(args, dict) else None


async def _complete(messages: list[dict], key: str) -> dict:
    """One forced-tool-call chat completion against the litellm proxy."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "tools": [_EMIT_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "emit_tool_schema"}},
    }
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMAssistError(f"litellm request failed: {e}") from e
    if resp.status_code >= 400:
        raise LLMAssistError(f"litellm returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _repair_message(prior: dict, errors: list[str]) -> dict:
    """A user turn that shows the invalid schema + its errors and asks for a fix."""
    return {
        "role": "user",
        "content": (
            "Your previous emit_tool_schema output failed validation:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nHere is what you returned:\n"
            + json.dumps(prior, indent=2)
            + "\n\nCall emit_tool_schema again with every problem fixed. Remember: "
            "`enum` must be a list of the allowed values, not a count."
        ),
    }


async def generate_tool_schema_llm(help_text: str, name: str) -> dict:
    """Ask the LLM for a structured neutral tool-call core, repairing invalid
    output against ``validate_tool_schema_core`` until it passes (up to
    ``_MAX_ATTEMPTS``). Raises ``LLMAssistError`` on config/upstream failure or if
    it can't be made valid."""
    key = read_secret(settings.llm_api_key_secret)
    if not key:
        raise LLMAssistError(
            f"LLM assist enabled but secret '{settings.llm_api_key_secret}' is unset."
        )
    base = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Tool name: {name}\n\n--- help ---\n{help_text}"},
    ]
    messages = list(base)
    errors = ["model did not call emit_tool_schema with JSON arguments"]
    for _attempt in range(_MAX_ATTEMPTS):
        data = await _complete(messages, key)
        args = _extract_args(data)
        if args is not None:
            # Pin the name we were given so a model name-drift never costs a repair.
            args["name"] = name
            errors = validate_tool_schema_core(args)
            if not errors:
                return args
        # Rebuild from base + a single repair turn (avoids provider-specific
        # tool_call/tool_result threading; each repair is a fresh forced call).
        messages = [*base, _repair_message(args or {}, errors)]
    raise LLMAssistError(
        f"could not produce a valid schema after {_MAX_ATTEMPTS} attempts: "
        + "; ".join(errors)
    )
