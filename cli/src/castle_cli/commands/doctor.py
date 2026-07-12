"""castle doctor — diagnose whether this node is set up and running.

Read-only. It answers the question the runtime status view can't: *is this node
correctly configured, and if not, what's the exact next command?* Runs a series
of checks grouped into Environment, Configuration, Runtime, and TLS & exposure;
each check reports ok / warn / fail with a one-line hint when action is needed.

Exit code: 0 when nothing FAILed (warnings are allowed), 1 otherwise — so it
doubles as a scriptable smoke test after `./install.sh` or `castle apply`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"

_ICON = {
    OK: "\033[32m✓\033[0m",
    WARN: "\033[33m!\033[0m",
    FAIL: "\033[31m✗\033[0m",
}

_GATEWAY = "castle-gateway"
_API = "castle-api"
_DASHBOARD = "castle"


@dataclass
class Check:
    status: str
    label: str
    detail: str = ""
    hint: str = ""


def _print(check: Check) -> None:
    line = f"  {_ICON[check.status]} {check.label}"
    if check.detail:
        line += f"  \033[90m{check.detail}\033[0m"
    print(line)
    if check.hint and check.status != OK:
        print(f"      \033[90m→ {check.hint}\033[0m")


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# --- Environment ------------------------------------------------------------


def _check_environment() -> list[Check]:
    checks: list[Check] = []

    if shutil.which("castle"):
        checks.append(Check(OK, "castle CLI on PATH"))
    else:
        checks.append(
            Check(
                WARN,
                "castle CLI not on PATH",
                hint="ensure ~/.local/bin is on PATH (uv tool install target)",
            )
        )

    if shutil.which("uv"):
        checks.append(Check(OK, "uv installed"))
    else:
        checks.append(
            Check(FAIL, "uv not found", hint="curl -LsSf https://astral.sh/uv/install.sh | sh")
        )

    checks.append(_check_lingering())
    return checks


def _check_lingering() -> Check:
    import getpass
    import subprocess

    user = getpass.getuser()
    try:
        out = subprocess.run(
            ["loginctl", "show-user", user],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return Check(WARN, "systemd lingering unknown", detail="loginctl not found")
    if "Linger=yes" in out.stdout:
        return Check(OK, "systemd user lingering enabled")
    return Check(
        WARN,
        "systemd user lingering off",
        detail="services stop when you log out",
        hint=f"sudo loginctl enable-linger {user}",
    )


# --- Configuration ----------------------------------------------------------


def _check_configuration(config) -> list[Check]:
    checks: list[Check] = []

    gw = config.gateway
    tls = (gw.tls or "off").lower()
    checks.append(
        Check(
            OK,
            "castle.yaml loaded",
            detail=f"gateway :{gw.port}, tls={tls}"
            + (f", domain={gw.domain}" if gw.domain else ""),
        )
    )

    if config.repo:
        checks.append(Check(OK, "repo: set", detail=str(config.repo)))
    else:
        checks.append(
            Check(
                FAIL,
                "repo: not set in castle.yaml",
                detail="source: repo:<name> cannot resolve castle's own programs",
                hint="add 'repo: <path-to-castle-checkout>' to ~/.castle/castle.yaml",
            )
        )

    # data dir must exist and be writable — the exact condition that crashes apply
    # (ensure_dirs) when data_dir points at a non-existent volume like /data.
    ddir = config.data_dir
    if ddir.is_dir() and os.access(ddir, os.W_OK):
        checks.append(Check(OK, "data dir writable", detail=str(ddir)))
    else:
        checks.append(
            Check(
                FAIL,
                "data dir missing or not writable",
                detail=str(ddir),
                hint=f"set data_dir: in ~/.castle/castle.yaml, or: "
                f"sudo mkdir -p {ddir} && sudo chown $(id -un) {ddir}",
            )
        )

    # Drift guard: castle.yaml is the single source of truth for the roots. An env var
    # override is per-process, so it's the one way the CLI and the api service can still
    # diverge (env set in your shell, absent in the service unit — the original bug).
    for var in ("CASTLE_DATA_DIR", "CASTLE_REPOS_DIR"):
        if var in os.environ:
            checks.append(
                Check(
                    WARN,
                    f"{var} overrides castle.yaml",
                    detail=f"{var}={os.environ[var]}",
                    hint=f"set data_dir:/repos_dir: in castle.yaml and unset {var}, so "
                    "every process (CLI and api) resolves the same roots",
                )
            )

    missing = [n for n in (_GATEWAY, _API, _DASHBOARD) if not config.deployments_named(n)]
    if not missing:
        checks.append(Check(OK, "control plane registered", detail="gateway, api, dashboard"))
    else:
        checks.append(
            Check(
                FAIL,
                "control plane missing",
                detail=", ".join(missing),
                hint="re-run ./install.sh (it seeds the control plane from bootstrap/)",
            )
        )

    checks.append(_check_dashboard_built(config))
    return checks


def _check_dashboard_built(config) -> Check:
    from castle_core.lifecycle import _static_built

    if not config.deployments_named(_DASHBOARD):
        return Check(WARN, "dashboard not registered", detail="skipping build check")
    if _static_built(_DASHBOARD, config):
        return Check(OK, "dashboard built", detail="app/dist/")
    return Check(
        WARN,
        "dashboard not built",
        detail="gateway has no UI to serve at /",
        hint=f"castle program build {_DASHBOARD}",
    )


# --- Runtime ----------------------------------------------------------------


def _deployment_port(config, name: str) -> int | None:
    dep = next((d for _k, d in config.deployments_named(name)), None)
    expose = getattr(dep, "expose", None)
    http = getattr(expose, "http", None)
    internal = getattr(http, "internal", None)
    return getattr(internal, "port", None)


def _check_runtime(config) -> list[Check]:
    from castle_core.config import SPECS_DIR
    from castle_core.lifecycle import is_active

    checks: list[Check] = []

    # Gateway: active + actually listening on its port.
    gw_port = config.gateway.port
    if is_active(_GATEWAY, "service", config):
        if _port_open(gw_port):
            checks.append(Check(OK, "gateway running", detail=f"listening on :{gw_port}"))
        else:
            checks.append(
                Check(
                    WARN,
                    "gateway active but not listening",
                    detail=f":{gw_port} refused",
                    hint="castle gateway reload; check 'castle service logs castle-gateway'",
                )
            )
    else:
        checks.append(
            Check(
                FAIL,
                "gateway not running",
                hint="castle apply",
            )
        )

    # API: active + listening on its port.
    api_port = _deployment_port(config, _API)
    if is_active(_API, "service", config):
        if api_port and not _port_open(api_port):
            checks.append(
                Check(
                    WARN,
                    "castle-api active but not listening",
                    detail=f":{api_port} refused",
                    hint="castle service logs castle-api",
                )
            )
        else:
            detail = f"listening on :{api_port}" if api_port else ""
            checks.append(Check(OK, "castle-api running", detail=detail))
    else:
        checks.append(Check(FAIL, "castle-api not running", hint="castle apply"))

    # Generated artifacts.
    registry = SPECS_DIR / "registry.yaml"
    caddyfile = SPECS_DIR / "Caddyfile"
    if registry.exists() and caddyfile.exists():
        checks.append(Check(OK, "registry + Caddyfile generated"))
    else:
        missing = [p.name for p in (registry, caddyfile) if not p.exists()]
        checks.append(
            Check(
                FAIL,
                "generated specs missing",
                detail=", ".join(missing),
                hint="castle apply",
            )
        )

    return checks


# --- TLS & exposure ---------------------------------------------------------


def _check_tls_exposure(config) -> list[Check]:
    checks: list[Check] = []
    gw = config.gateway
    tls = (gw.tls or "off").lower()

    if tls == "acme":
        provider = gw.acme_dns_provider or "cloudflare"

        if not gw.domain:
            checks.append(
                Check(
                    FAIL,
                    "tls=acme but no domain set",
                    hint="add 'domain: <your-zone>' under gateway: in castle.yaml",
                )
            )

        # DNS-plugin Caddy (stock apt Caddy has no DNS-01 modules).
        plugin = Path("/usr/local/bin/caddy")
        module = f"dns.providers.{provider}"
        has_module = False
        if plugin.exists():
            import subprocess

            out = subprocess.run(
                [str(plugin), "list-modules"],
                capture_output=True,
                text=True,
                check=False,
            )
            has_module = module in out.stdout
        if has_module:
            checks.append(Check(OK, "DNS-plugin Caddy present", detail=module))
        else:
            checks.append(
                Check(
                    FAIL,
                    "DNS-plugin Caddy missing",
                    detail=f"need {module} at /usr/local/bin/caddy",
                    hint=f"./install.sh --with-dns-plugin={provider}",
                )
            )

        # Provider token secret.
        token_name = {"cloudflare": "CLOUDFLARE_API_TOKEN"}.get(
            provider, f"{provider.upper()}_API_TOKEN"
        )
        from castle_core.config import read_secret

        if read_secret(token_name):
            checks.append(Check(OK, "provider token present", detail=token_name))
        else:
            checks.append(
                Check(
                    FAIL,
                    "provider token missing",
                    detail=token_name,
                    hint="set it via the dashboard Secrets page (or the file/vault backend)",
                )
            )

        # Can the gateway bind :443/:80?
        checks.append(_check_privileged_ports())

    # Public exposure (only relevant if a deployment opts in).
    public_specs = [(n, d) for _k, n, d in config.all_deployments() if getattr(d, "public", False)]
    public = [n for n, _d in public_specs]
    if public:
        from castle_core.lifecycle import is_active

        # A public deployment gets its public name from its own `public_host`
        # override or the node-wide `public_domain`; the default domain is only
        # required if some public deployment relies on it.
        need_default = any(not getattr(d, "public_host", None) for _n, d in public_specs)
        if gw.tunnel_id and (gw.public_domain or not need_default):
            checks.append(Check(OK, "tunnel configured", detail=f"{len(public)} public service(s)"))
        else:
            missing = []
            if need_default and not gw.public_domain:
                missing.append("public_domain")
            if not gw.tunnel_id:
                missing.append("tunnel_id")
            checks.append(
                Check(
                    FAIL,
                    "public services but tunnel unconfigured",
                    detail="missing " + ", ".join(missing),
                    hint="see docs/tunnel-setup.md",
                )
            )
        if not is_active("castle-tunnel", "service", config):
            checks.append(
                Check(
                    WARN,
                    "castle-tunnel not running",
                    detail="public routes are down",
                    hint="enable castle-tunnel in its deployment, then: castle apply",
                )
            )
        checks.append(_check_public_dns(config))

    if not checks:
        checks.append(Check(OK, "off mode — no TLS/exposure to check", detail="localhost only"))
    return checks


def _check_public_dns(config) -> Check:
    """Whether Castle can manage the public CNAMEs itself.

    Read-only: confirms the token exists and can reach the public zone + its DNS
    records. The required permission is a single DNS:Edit (Cloudflare's 'Edit zone
    DNS' template), which also grants the zone lookup — so a correctly-scoped token
    passes this probe. Write itself isn't exercised (that would mutate); a
    DNS:Read-only token would false-pass here but `castle apply` then surfaces a
    403 with the fix. Absent token → WARN (CNAMEs stay manual), not a failure.
    """
    import urllib.error

    from castle_core.generators.dns import PUBLIC_DNS_TOKEN, _api, public_dns_token

    gw = config.gateway
    token = public_dns_token()
    if not token:
        return Check(
            WARN,
            "public DNS not automated",
            detail=f"no {PUBLIC_DNS_TOKEN} secret — CNAMEs are manual",
            hint=(
                f"add a Cloudflare token with DNS:Edit on "
                f"{gw.public_domain or 'the public zone(s)'} "
                f"('Edit zone DNS' template) → ~/.castle/secrets/{PUBLIC_DNS_TOKEN} "
                "(else route each host by hand)"
            ),
        )
    try:
        # With a node-wide public_domain, probe that specific zone; otherwise
        # (custom public_host hosts only) confirm the token can list *some* zone —
        # reconcile resolves each host's zone by longest-suffix match at apply.
        query = f"/zones?name={gw.public_domain}" if gw.public_domain else "/zones?per_page=1"
        zres = (_api(token, "GET", query).get("result")) or []
        if not zres:
            where = gw.public_domain or "any zone"
            return Check(
                FAIL,
                "public DNS token can't see the zone",
                detail=f"{where} not visible",
                hint=(
                    f"token needs DNS:Edit scoped to {where}, in that "
                    "zone's account ('Edit zone DNS' template)"
                ),
            )
        zid = zres[0]["id"]
        _api(token, "GET", f"/zones/{zid}/dns_records?type=CNAME&per_page=1")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return Check(
                FAIL,
                "public DNS token lacks DNS access",
                detail="zone readable but DNS records forbidden (403)",
                hint="add DNS:Edit to the token (Cloudflare 'Edit zone DNS' template)",
            )
        return Check(WARN, "public DNS token check inconclusive", detail=f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 — never let a network hiccup fail doctor
        return Check(WARN, "public DNS token check inconclusive", detail=str(e)[:60])
    return Check(
        OK,
        "public DNS token valid",
        detail=f"can reach {gw.public_domain or 'its zones'} + records",
    )


def _check_privileged_ports() -> Check:
    try:
        val = int(Path("/proc/sys/net/ipv4/ip_unprivileged_port_start").read_text().strip())
    except (OSError, ValueError):
        return Check(WARN, "cannot read unprivileged port floor")
    if val <= 80:
        return Check(OK, "can bind :80/:443", detail=f"unprivileged floor {val}")
    return Check(
        WARN,
        "cannot bind :80/:443",
        detail=f"unprivileged floor is {val}",
        hint="echo 'net.ipv4.ip_unprivileged_port_start=80' | "
        "sudo tee /etc/sysctl.d/50-castle-gateway.conf && sudo sysctl --system",
    )


# --- Driver -----------------------------------------------------------------


def _check_stacks(config: object) -> list[Check]:
    """Stack toolchains: is each *in-use* stack's host tooling present where its
    programs need it (run-phase tools against the service's runtime PATH)? A missing
    tool for an enabled deployment is a FAIL (its service can't build/run); missing
    for a not-yet-enabled program is a WARN. Unused stacks are skipped — no nagging
    about pnpm when there are no frontends."""
    from castle_core.stack_status import all_stack_status

    checks: list[Check] = []
    for st in all_stack_status(config, with_version=False):
        if not st.in_use or not st.tools:
            continue
        n = len(st.programs)
        label = f"{st.name}  ({n} program{'s' if n != 1 else ''})"
        missing = [t for t in st.tools if not t.present]
        if not missing:
            present = ", ".join(t.command for t in st.tools)
            checks.append(Check(OK, label, detail=f"{present} present"))
            continue
        status = FAIL if st.has_enabled_deployment else WARN
        checks.append(
            Check(
                status,
                label,
                detail="missing: " + ", ".join(t.command for t in missing),
                hint=missing[0].install_hint,
            )
        )
    if not checks:
        checks.append(Check(OK, "no stack toolchains in use"))
    return checks


def run_doctor(args: argparse.Namespace) -> int:
    from castle_core.config import load_config

    print("\n\033[1mCastle Doctor\033[0m")

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — surface any load failure as the first FAIL
        print("\n\033[1mConfiguration\033[0m")
        _print(
            Check(
                FAIL,
                "castle.yaml failed to load",
                detail=str(exc),
                hint="check ~/.castle/castle.yaml — re-run ./install.sh to reseed",
            )
        )
        print()
        return 1

    sections: list[tuple[str, list[Check]]] = [
        ("Environment", _check_environment()),
        ("Configuration", _check_configuration(config)),
        ("Stacks & dependencies", _check_stacks(config)),
        ("Runtime", _check_runtime(config)),
        ("TLS & exposure", _check_tls_exposure(config)),
    ]

    fails = warns = 0
    for title, checks in sections:
        print(f"\n\033[1m{title}\033[0m")
        for check in checks:
            _print(check)
            fails += check.status == FAIL
            warns += check.status == WARN

    print()
    if fails:
        print(f"\033[31m{fails} problem(s)\033[0m" + (f", {warns} warning(s)" if warns else ""))
        return 1
    if warns:
        print(f"\033[33m{warns} warning(s)\033[0m — Castle is up; address when convenient")
        return 0
    print("\033[32mAll checks passed.\033[0m")
    return 0
