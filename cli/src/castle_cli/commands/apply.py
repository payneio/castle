"""castle apply — converge the running system to match config.

The one workhorse verb: renders systemd units + the Caddyfile + tunnel config,
then reconciles the runtime (activate what's enabled and down, restart what
changed, deactivate what's disabled). Replaces the old `deploy && start` plus the
per-kind enable/disable/install/uninstall verbs.

`--plan` computes and prints the diff without writing or touching the runtime.
"""

from __future__ import annotations

import argparse

_C = {
    "activate": "\033[32m",  # green
    "restart": "\033[33m",  # yellow
    "deactivate": "\033[31m",  # red
    "reset": "\033[0m",
    "dim": "\033[90m",
}


def _line(verb_color: str, verb: str, names: list[str]) -> None:
    if not names:
        return
    print(f"  {verb_color}{verb}{_C['reset']}  {', '.join(sorted(names))}")


def run_apply(args: argparse.Namespace) -> int:
    from castle_core.deploy import apply

    target = getattr(args, "name", None)
    plan = getattr(args, "plan", False)

    result = apply(target_name=target, plan=plan)

    # Surface any warnings the render produced (acme prerequisites, tunnel notes).
    for msg in result.messages:
        if msg.startswith("Warning"):
            print(f"  {_C['dim']}{msg}{_C['reset']}")

    if plan:
        print("\n\033[1mPlan\033[0m " + _C["dim"] + "(no changes made)" + _C["reset"])
        if not result.changed:
            print(f"  {_C['dim']}nothing to do — already converged{_C['reset']}")
            return 0
        _line(_C["activate"], "would activate  ", result.activated)
        _line(_C["restart"], "would restart   ", result.restarted)
        _line(_C["deactivate"], "would deactivate", result.deactivated)
        return 0

    print("\n\033[1mApplied\033[0m")
    if not result.changed:
        print(f"  {_C['dim']}nothing to do — already converged{_C['reset']}")
        return 0
    _line(_C["activate"], "activated  ", result.activated)
    _line(_C["restart"], "restarted  ", result.restarted)
    _line(_C["deactivate"], "deactivated", result.deactivated)
    return 0
