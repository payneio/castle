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

    missing = [n for n in (_GATEWAY, _API, _DASHBOARD) if n not in config.deployments]
    if not missing:
        checks.append(
            Check(OK, "control plane registered", detail="gateway, api, dashboard")
        )
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

    if _DASHBOARD not in config.deployments:
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
    dep = config.deployments.get(name)
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
    if is_active(_GATEWAY, config):
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
    if is_active(_API, config):
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
        checks.append(
            Check(FAIL, "castle-api not running", hint="castle apply")
        )

    # Generated artifacts.
    registry = SPECS_DIR / "registry.yaml"
    caddyfile = SPECS_DIR / "Caddyfile"
    if registry.exists() and caddyfile.exists():
        checks.append(Check(OK, "registry + Caddyfile generated"))
    else:
        missing = [
            p.name for p in (registry, caddyfile) if not p.exists()
        ]
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
    from castle_core.config import SECRETS_DIR

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
        if (SECRETS_DIR / token_name).exists():
            checks.append(Check(OK, "provider token present", detail=token_name))
        else:
            checks.append(
                Check(
                    FAIL,
                    "provider token missing",
                    detail=f"~/.castle/secrets/{token_name}",
                    hint=f"printf '%s' <token> > ~/.castle/secrets/{token_name} && chmod 600 $_",
                )
            )

        # Can the gateway bind :443/:80?
        checks.append(_check_privileged_ports())

    # Public exposure (only relevant if a deployment opts in).
    public = [n for n, d in config.deployments.items() if getattr(d, "public", False)]
    if public:
        from castle_core.lifecycle import is_active

        if gw.public_domain and gw.tunnel_id:
            checks.append(
                Check(OK, "tunnel configured", detail=f"{len(public)} public service(s)")
            )
        else:
            missing = []
            if not gw.public_domain:
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
        if not is_active("castle-tunnel", config):
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
                f"add a Cloudflare token with DNS:Edit on {gw.public_domain} "
                f"('Edit zone DNS' template) → ~/.castle/secrets/{PUBLIC_DNS_TOKEN} "
                "(else route each host by hand)"
            ),
        )
    try:
        zres = (_api(token, "GET", f"/zones?name={gw.public_domain}").get("result")) or []
        if not zres:
            return Check(
                FAIL,
                "public DNS token can't see the zone",
                detail=f"{gw.public_domain} not visible",
                hint=(
                    f"token needs DNS:Edit scoped to {gw.public_domain}, in that "
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
        detail=f"can reach {gw.public_domain} + its records",
    )


def _check_privileged_ports() -> Check:
    try:
        val = int(
            Path("/proc/sys/net/ipv4/ip_unprivileged_port_start").read_text().strip()
        )
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
