"""Deploy logic — bridge castle.yaml spec to runtime (~/.castle/).

This module contains the core deploy logic shared by the CLI and API.
It reads castle.yaml, resolves services/jobs into Deployments,
writes the registry, generates systemd units and the Caddyfile, and
copies frontend build outputs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from castle_core.config import (
    SPECS_DIR,
    CastleConfig,
    ensure_dirs,
    load_config,
    resolve_env_split,
    resolve_placeholders,
)
from castle_core.generators.caddyfile import (
    _DNS_TOKEN_ENV,
    generate_caddyfile_from_registry,
)
from castle_core.generators.dns import reconcile_public_dns
from castle_core.generators.tunnel import (
    generate_tunnel_config,
    public_hostnames,
)
from castle_core.generators.systemd import (
    SECRET_ENV_DIR,
    generate_timer,
    generate_unit_from_deployed,
    secret_env_path,
    timer_name,
    unit_env_file,
    unit_name,
)
from castle_core.manifest import (
    CaddyDeployment,
    DeploymentBase,
    DeploymentSpec,
    PathDeployment,
    RemoteDeployment,
    TlsMaterial,
    kind_for,
)
from castle_core.registry import (
    REGISTRY_PATH,
    Deployment,
    NodeConfig,
    NodeRegistry,
    load_registry,
    save_registry,
)
from castle_core.toolchains import ToolchainError, resolve_node_bin

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


@dataclass
class DeployResult:
    """Result of a deploy operation."""

    deployed_count: int = 0
    messages: list[str] = field(default_factory=list)
    registry: NodeRegistry | None = None


@dataclass
class ApplyResult:
    """Result of a converge (`castle apply`): what actually changed.

    `deploy` renders config → artifacts; `apply` renders *and then* reconciles the
    running system to match, so the interesting output is the diff it enacted.
    """

    activated: list[str] = field(default_factory=list)
    restarted: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    registry: NodeRegistry | None = None
    # Gateway routing (the Caddyfile / cloudflared ingress) differs from what's live:
    # a caddy static/proxy route was added, removed, or had its root/reach changed.
    # Tracked separately because such a delta touches no systemd unit, so the
    # activate/restart/deactivate reconcile never classifies it as a change. apply()
    # rewrites the artifacts and reloads the gateway regardless; this flag just lets
    # the summary report it instead of a false "already converged".
    gateway_changed: bool = False
    # True for a `--plan` run: the diff was computed but nothing was written or
    # activated. Lets callers render "would activate…" vs "activated…".
    planned: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.activated
            or self.restarted
            or self.deactivated
            or self.pruned
            or self.gateway_changed
        )


def deploy(target_name: str | None = None, root: Path | None = None) -> DeployResult:
    """Deploy from castle.yaml to ~/.castle/.

    Args:
        target_name: Deploy a single service/job by name, or None for all.
        root: Config root path. If None, uses find_castle_root().

    Returns:
        DeployResult with deployed count, messages, and the registry.
    """
    config = load_config(root)
    result = DeployResult()

    ensure_dirs(config)

    # Build node config
    node = _node_config(config)

    # Load existing registry to preserve entries not being redeployed,
    # or start fresh if deploying all
    if target_name and REGISTRY_PATH.exists():
        try:
            existing = load_registry()
            registry = NodeRegistry(node=node, deployed=dict(existing.deployed))
        except (FileNotFoundError, ValueError):
            registry = NodeRegistry(node=node)
    else:
        registry = NodeRegistry(node=node)

    # Deploy every deployment, dispatched by its manager (systemd/caddy/path/none).
    # target_name (if given) matches every kind sharing that bare name.
    for _kind, name, dep in config.all_deployments():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed(config, name, dep, result.messages)
        deployed.name = name
        registry.put(deployed)
        result.deployed_count += 1
        result.messages.append(_format_deployed(name, deployed))

    # Static frontends are served in place from their repo build output
    # (the Caddyfile roots directly at <source>/<dist>) — no copy step.

    # Save registry
    save_registry(registry)
    result.messages.append(f"Registry written: {REGISTRY_PATH}")

    # Generate systemd units from registry
    _generate_systemd_units(config, registry)
    result.messages.append(f"Systemd units written: {SYSTEMD_USER_DIR}")

    # Converge: prune orphan units (full deploy only — partial deploys preserve siblings)
    if target_name is None:
        _prune_orphans(registry, result.messages)

    # Generate Caddyfile from registry
    caddyfile_path = SPECS_DIR / "Caddyfile"
    caddyfile_content = generate_caddyfile_from_registry(registry)
    caddyfile_path.write_text(caddyfile_content)
    result.messages.append(f"Caddyfile written: {caddyfile_path}")

    # Generate the cloudflared tunnel ingress from the registry's public services.
    _write_tunnel_config(registry, result.messages)

    # acme mode needs a domain + a DNS-provider token; warn (don't fail) if the
    # prerequisites the operator must set up by hand are missing.
    if (config.gateway.tls or "").lower() == "acme":
        _acme_preflight(config, result.messages)

    # Reload systemd daemon
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    # Reload the gateway so the freshly written Caddyfile takes effect. Without
    # this, new/changed proxy routes sit on disk but the running Caddy keeps the
    # old config (a deployed service's route is silently dead until reload).
    _reload_gateway(config, result.messages)

    result.registry = registry
    return result


def _node_config(config: CastleConfig) -> NodeConfig:
    """The registry NodeConfig derived from a config's gateway settings."""
    return NodeConfig(
        castle_root=str(config.root),
        gateway_port=config.gateway.port,
        gateway_tls=config.gateway.tls,
        gateway_domain=config.gateway.domain,
        acme_email=config.gateway.acme_email,
        acme_dns_provider=config.gateway.acme_dns_provider,
        public_domain=config.gateway.public_domain,
        tunnel_id=config.gateway.tunnel_id,
        cert_hook=config.gateway.cert_hook,
        role=config.role,
    )


def _unit_file_for(name: str, kind: str) -> Path:
    """On-disk systemd unit path for a deployment (timer if it's a job)."""
    return SYSTEMD_USER_DIR / (
        timer_name(name) if kind == "job" else unit_name(name, kind)
    )


def _unit_bytes(name: str, kind: str) -> str | None:
    """Current unit-file contents, or None if it isn't written yet."""
    path = _unit_file_for(name, kind)
    return path.read_text() if path.exists() else None


def _desired_registry(config: CastleConfig, target_name: str | None) -> NodeRegistry:
    """The registry ``deploy()`` would write for this (optionally scoped) run.

    Mirrors deploy()'s registry build: a scoped run merges the updated target over
    the existing on-disk registry; a full run starts fresh. Used to predict
    gateway-route deltas without writing anything."""
    node = _node_config(config)
    if target_name and REGISTRY_PATH.exists():
        try:
            registry = NodeRegistry(node=node, deployed=dict(load_registry().deployed))
        except (FileNotFoundError, ValueError):
            registry = NodeRegistry(node=node)
    else:
        registry = NodeRegistry(node=node)
    for _kind, name, dep in config.all_deployments():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed(config, name, dep, [])
        deployed.name = name
        registry.put(deployed)
    return registry


def _gateway_would_change(config: CastleConfig, target_name: str | None) -> bool:
    """Whether applying would rewrite the gateway's routing artifacts — the
    Caddyfile or the cloudflared ingress — vs. what's on disk.

    A pure caddy route change (new static, changed ``root``/``reach``, toggled
    public) touches no systemd unit, so the activate/restart/deactivate reconcile
    can't see it; without this the summary reports "already converged" despite a
    live routing change. Compared before ``deploy()`` rewrites the artifacts, so it
    reflects the pre-apply delta for both the plan and the real run."""
    registry = _desired_registry(config, target_name)
    caddyfile = SPECS_DIR / "Caddyfile"
    current_caddy = caddyfile.read_text() if caddyfile.exists() else None
    if generate_caddyfile_from_registry(registry) != current_caddy:
        return True
    tunnel_path = SPECS_DIR / "cloudflared.yml"
    current_tunnel = tunnel_path.read_text() if tunnel_path.exists() else None
    return generate_tunnel_config(registry) != current_tunnel


def apply(
    target_name: str | None = None,
    root: Path | None = None,
    plan: bool = False,
) -> ApplyResult:
    """Converge the running system to match config — the one honest bring-up.

    `apply` = `deploy` (render units/Caddyfile/tunnel) **plus** reconcile: activate
    every enabled deployment that isn't live, restart any whose unit changed,
    deactivate the disabled ones. It replaces the old two-step ``deploy && start``
    and the per-kind enable/disable/install verbs — the mechanism varies by manager
    (systemd unit / PATH install / gateway route), the verb never does.

    `plan=True` computes and returns the diff **without writing or touching the
    runtime** (the ``--plan`` dry run).
    """
    import asyncio

    from castle_core.lifecycle import activate, deactivate, is_active

    config = load_config(root)
    # Each item is (kind, name, spec); target_name matches every kind of that name.
    # Identity is (kind, name) — two kinds may share a bare name.
    items = [
        (k, n, d)
        for k, n, d in config.all_deployments()
        if not target_name or n == target_name
    ]
    names = [n for _k, n, _d in items]

    # Snapshot BEFORE rendering: liveness + current unit bytes (for restart-on-change).
    before_active = {(k, n): is_active(n, k, config) for k, n, _ in items}
    before_unit = {(k, n): _unit_bytes(n, k) for k, n, _ in items}

    # Desired state, rendered in memory to classify each deployment. For a real run
    # this is recomputed by deploy() below (which also writes it); cheap and keeps
    # the plan/apply classification identical.
    desired: dict[tuple[str, str], Deployment] = {}
    for k, n, spec in items:
        dep = _build_deployed(config, n, spec, [])
        dep.name = n
        desired[(k, n)] = dep

    def _classify(ident: tuple[str, str], after_unit: str | None) -> str:
        dep = desired[ident]
        if not dep.enabled:
            return "deactivate" if before_active[ident] else "unchanged"
        if not before_active[ident]:
            return "activate"
        if dep.manager == "systemd" and before_unit[ident] != after_unit:
            return "restart"
        return "unchanged"

    result = ApplyResult(
        registry=NodeRegistry(
            node=_node_config(config),
            deployed={NodeRegistry.key(k, n): d for (k, n), d in desired.items()},
        )
    )
    # Gateway routing lives in the Caddyfile / cloudflared ingress, not a systemd
    # unit, so _classify above can't see a route-only change. Detect it here against
    # the on-disk artifacts (before deploy() rewrites them) so both the plan and the
    # real run report it instead of a false "already converged".
    result.gateway_changed = _gateway_would_change(config, target_name)

    if plan:
        # No writes: for systemd, predict the new unit bytes by rendering to a string
        # so "would restart" is accurate; other managers never restart.
        result.planned = True
        _stack_preflight(config, items, result.messages)
        for k, n, _ in items:
            after = _render_unit_preview(config, n, desired[(k, n)], k)
            _record(result, n, _classify((k, n), after))
        return result

    # Real run: render everything (writes units/Caddyfile/tunnel, daemon-reload,
    # gateway reload, orphan prune), then reconcile the runtime.
    deploy_result = deploy(target_name, root)
    result.messages = list(deploy_result.messages)
    result.registry = deploy_result.registry
    _stack_preflight(config, items, result.messages)

    # Materialize TLS cert files before (re)starting so a TLS service finds them on
    # start. On a fresh node the gateway reload above only kicks off ACME issuance,
    # so wait (bounded) for the wildcard first — otherwise the service would start
    # without its cert and, with cert_hook off (the default), never recover. Scope
    # materialization to the deployments being applied so a scoped apply doesn't
    # rewrite an unrelated service's cert without reloading it. No reload here — the
    # activation loop below starts/restarts as needed; rotation-driven reloads are
    # the `castle tls reconcile` / cert_obtained path.
    from castle_core.tls import materialize_all, wait_for_wildcard

    wait_for_wildcard(config, names, result.messages)
    materialize_all(config, result.messages, only=names)

    for k, n, _ in items:
        after_unit = _unit_bytes(n, k)
        action = _classify((k, n), after_unit)
        if action == "activate":
            asyncio.run(activate(n, k, config, config.root))
            result.activated.append(n)
        elif action == "deactivate":
            asyncio.run(deactivate(n, k, config, config.root))
            result.deactivated.append(n)
        elif action == "restart":
            unit = timer_name(n) if k == "job" else unit_name(n, k)
            subprocess.run(["systemctl", "--user", "restart", unit], check=False)
            result.restarted.append(n)
        else:
            result.unchanged.append(n)

    return result


def _stack_preflight(
    config: CastleConfig,
    items: Sequence[tuple[str, str, object]],
    messages: list[str],
) -> None:
    """Warn (never fail) when an enabled deployment's stack toolchain is missing
    *where it runs* — the moment drift actually bites: a service whose `uv`/`pnpm`
    isn't on its runtime PATH won't build or start. Mirrors `_acme_preflight`: an
    advisory message, no writes, no gate. The exact fix comes from the tool's hint."""
    from castle_core.relations import _tool_available
    from castle_core.stacks import tools_for

    for _k, n, spec in items:
        if not getattr(spec, "enabled", True):
            continue
        prog = config.programs.get(getattr(spec, "program", None) or n)
        if not prog or not prog.stack:
            continue
        for tool in tools_for(prog.stack):
            if not _tool_available(spec, tool):
                messages.append(
                    f"Warning: {n} ({prog.stack}) needs '{tool.command}' but it's "
                    f"missing where the service runs — {tool.install_hint}"
                )


def _record(result: ApplyResult, name: str, action: str) -> None:
    {
        "activate": result.activated,
        "deactivate": result.deactivated,
        "restart": result.restarted,
        "unchanged": result.unchanged,
    }[action].append(name)


def _render_unit_preview(
    config: CastleConfig, name: str, dep: Deployment, kind: str
) -> str | None:
    """The unit bytes `deploy` would write for the deployment we'd restart (the
    .timer for a job, the .service for a service), for --plan restart detection.
    None when there's no unit to compare (non-systemd, or unmanaged)."""
    files = _render_unit_files(config, name, dep)
    if not files:
        return None
    return files.get(timer_name(name) if kind == "job" else unit_name(name, kind))


# Gateway service name in the registry → its systemd unit (castle-castle-gateway).
_GATEWAY_NAME = "castle-gateway"


def _acme_preflight(config: CastleConfig, messages: list[str]) -> None:
    """Warn (never fail, never write) if acme-mode prerequisites are missing.

    acme mode needs a `gateway.domain`, the DNS-provider token mapped into the
    castle-gateway service env, and the matching secret on disk — all operator
    steps (castle never rewrites the user-authored gateway service YAML)."""
    gw = config.gateway
    if not gw.domain:
        messages.append(
            "Warning: gateway.tls=acme but gateway.domain is unset — host routes "
            "won't get a wildcard cert (serving plain HTTP on the gateway port)."
        )
        return
    token_env = _DNS_TOKEN_ENV.get(
        gw.acme_dns_provider or "cloudflare", "CLOUDFLARE_API_TOKEN"
    )
    svc = config.services.get(_GATEWAY_NAME)
    env = dict(svc.defaults.env) if (svc and svc.defaults and svc.defaults.env) else {}
    if token_env not in env:
        messages.append(
            f"Warning: acme mode needs {token_env} in the {_GATEWAY_NAME} service env. "
            f"Add to services/{_GATEWAY_NAME}.yaml → defaults.env: "
            f"{token_env}: ${{secret:{token_env}}}"
        )
    from castle_core.config import read_secret

    if not read_secret(token_env):
        messages.append(
            f"Warning: secret '{token_env}' is not set in the secret backend — add "
            f"the DNS-provider API token (Cloudflare token scope: Zone:DNS:Edit)."
        )


# Tunnel service name in the registry → its systemd unit (castle-castle-tunnel).
_TUNNEL_NAME = "castle-tunnel"


def _write_tunnel_config(registry: NodeRegistry, messages: list[str]) -> None:
    """Write the cloudflared ingress config from the registry's public services.

    No public services (or no tunnel configured) → remove any stale config and
    leave the tunnel down. Otherwise write it and restart the tunnel service if
    it's running so it takes effect. Either way the public CNAMEs are reconciled to
    match the current public set (create missing, delete removed) when a DNS token
    is configured; without one, the manual route-once commands are surfaced instead.
    """
    node = registry.node
    config_path = SPECS_DIR / "cloudflared.yml"
    content = generate_tunnel_config(registry)
    if content is None:
        if config_path.exists():
            config_path.unlink()
            messages.append("No public services — removed cloudflared config.")
        # Still reconcile so any CNAMEs castle created earlier are cleaned up.
        reconcile_public_dns(node.tunnel_id, [], messages)
        return

    config_path.write_text(content)
    hosts = public_hostnames(registry)
    messages.append(f"Tunnel config written: {config_path} ({len(hosts)} public)")
    # Reconcile the public CNAMEs to the tunnel. Falls back to surfacing the manual
    # `cloudflared tunnel route dns` commands when no DNS token is configured.
    if not reconcile_public_dns(node.tunnel_id, hosts, messages):
        for h in hosts:
            messages.append(
                f"  public: {h}  "
                f"(route once: cloudflared tunnel route dns {node.tunnel_id} {h})"
            )

    tunnel_unit = unit_name(_TUNNEL_NAME)
    active = subprocess.run(
        ["systemctl", "--user", "is-active", tunnel_unit],
        capture_output=True,
        text=True,
    )
    if active.stdout.strip() == "active":
        subprocess.run(["systemctl", "--user", "restart", tunnel_unit], check=False)
        messages.append("Tunnel reloaded.")
    else:
        messages.append(
            "Tunnel not running — enable it with 'castle service enable tunnel'."
        )


def _gateway_env(config: CastleConfig) -> dict[str, str]:
    """The process env for validating/handling the gateway's Caddyfile — the
    current environment plus the castle-gateway service's own resolved env.

    Under acme the Caddyfile references ``{env.CLOUDFLARE_API_TOKEN}`` (or another
    DNS-provider token). `caddy validate` provisions the acme module and rejects an
    empty token, so validating in castle-api's bare environment always fails and the
    reload is skipped. Injecting the gateway service's env (secrets resolved) gives
    validate the same token the running service starts with."""
    svc = config.services.get(_GATEWAY_NAME)
    raw = dict(svc.defaults.env) if (svc and svc.defaults and svc.defaults.env) else {}
    plain, secret = resolve_env_split(raw, None)
    resolved = {k: secret.get(k, plain.get(k, "")) for k in raw}
    return {**os.environ, **resolved}


def _reload_gateway(config: CastleConfig, messages: list[str]) -> None:
    """Reload Caddy if the gateway is running, so new routes take effect."""
    gw_unit = unit_name(_GATEWAY_NAME)
    # Validate the generated Caddyfile before reloading. An invalid config (most
    # often gateway.cert_hook enabled while the running Caddy lacks the events-exec
    # plugin, so the `events {}` block fails to adapt) must not be pushed: a bad
    # reload leaves stale routing and a later cold start would refuse to load. Skip
    # the reload and point at the likely cause instead of silently degrading.
    # Validate with the gateway's own env so acme's DNS-provider token resolves —
    # otherwise validation fails on an empty token and every reload is skipped.
    caddyfile = SPECS_DIR / "Caddyfile"
    caddy = shutil.which("caddy")
    if caddy and caddyfile.exists():
        check = subprocess.run(
            [caddy, "validate", "--adapter", "caddyfile", "--config", str(caddyfile)],
            capture_output=True,
            text=True,
            env=_gateway_env(config),
        )
        if check.returncode != 0:
            messages.append(
                "Warning: generated Caddyfile is invalid — gateway NOT reloaded (the "
                "running config is left untouched). If gateway.cert_hook is enabled, "
                "the gateway's Caddy build needs the events-exec plugin; rebuild it "
                "(install.sh) or set cert_hook: false.\n"
                + (check.stderr.strip() or check.stdout.strip())
            )
            return
    active = subprocess.run(
        ["systemctl", "--user", "is-active", gw_unit],
        capture_output=True,
        text=True,
    )
    if active.stdout.strip() != "active":
        messages.append(
            "Gateway not running — skipped reload (start it with 'castle gateway start')."
        )
        return
    result = subprocess.run(
        ["systemctl", "--user", "reload", gw_unit], capture_output=True, text=True
    )
    if result.returncode == 0:
        messages.append("Gateway reloaded.")
    else:
        messages.append(f"Warning: gateway reload failed: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _public_url(
    config: CastleConfig, name: str, exposed: bool, port: int | None
) -> str | None:
    """The service's publicly-reachable base URL — the ``${public_url}`` placeholder.

    When the service is exposed through the gateway under acme TLS, this is its
    trusted subdomain ``https://<name>.<gateway.domain>`` — the origin an app must
    allowlist for CORS/WebSocket/secure-context to work behind the gateway. It
    tracks ``gateway.domain`` automatically, so a domain change needs no app edit.
    Off mode / port-only falls back to the node-local ``http://localhost:<port>``;
    ``None`` when there's no port to reach it on (nothing to interpolate).
    """
    gw = config.gateway
    if exposed and str(gw.tls or "").lower() == "acme" and gw.domain:
        return f"https://{name}.{gw.domain}"
    if port is not None:
        return f"http://localhost:{port}"
    return None


def _target_url(config: CastleConfig, target_name: str) -> str | None:
    """The base URL another deployment is reachable at — how a ``{kind: deployment,
    bind: VAR}`` requirement projects its target into the consumer's env. A name may
    span kinds; the HTTP-exposed one is what has a URL, so prefer it."""
    matches = config.deployments_named(target_name)
    dep = next((s for _k, s in matches if getattr(s, "http_exposed", False)), None)
    if dep is None:
        dep = matches[0][1] if matches else None
    if dep is None:
        return None
    # A reference (manager: none) carries its URL directly — that's what a bind to
    # an external resource projects into the consumer's env.
    base = getattr(dep, "base_url", None)
    if base:
        return base
    expose = getattr(dep, "expose", None)
    http = getattr(expose, "http", None) if expose else None
    tport = http.internal.port if http else None
    return _public_url(config, target_name, getattr(dep, "http_exposed", False), tport)


def _requires_env(config: CastleConfig, dep: DeploymentSpec) -> dict[str, str]:
    """Env generated FROM a deployment's ``requires`` — a ``{ref, bind: VAR}``
    requirement sets ``VAR`` to the target deployment's URL. Env is derived from the
    dependency, never scraped back into one (see docs/relationships.md)."""
    out: dict[str, str] = {}
    for r in getattr(dep, "requires", []) or []:
        if r.kind == "deployment" and r.bind:
            url = _target_url(config, r.ref)
            if url:
                out[r.bind] = url
    return out


def _supabase_app_schemas(config: CastleConfig) -> str:
    """The ``${supabase_app_schemas}`` placeholder: each registered supabase app's
    own schema, comma-prefixed and joined (or '' when there are none).

    The substrate exposes app schemas through PostgREST by listing them in
    PGRST_DB_SCHEMAS; its deployment maps that env to
    ``public,storage,graphql_public${supabase_app_schemas}``. Comma-prefixing each
    entry keeps the base list valid when zero apps are registered (no trailing
    comma). Adding/removing a supabase app thus changes this list — the substrate
    needs a restart (recreate) after `castle deploy` to pick it up.
    """
    from castle_core.stacks import app_schema

    schemas = sorted(
        app_schema(pn) for pn, ps in config.programs.items() if ps.stack == "supabase"
    )
    return "".join(f",{s}" for s in schemas)


def _env_context(
    name: str,
    config_key: str,
    port: int | None,
    data_dir: Path,
    public_url: str | None = None,
    supabase_app_schemas: str | None = None,
) -> dict[str, str]:
    """Placeholder values for defaults.env: ${name}/${data_dir}/${port}/${public_url}/
    ${supabase_app_schemas}. `data_dir` is the instance root (config.data_dir)."""
    ctx = {
        "name": name,
        "data_dir": str(data_dir / config_key),
        "uid": str(os.getuid()),
        "gid": str(os.getgid()),
    }
    if port is not None:
        ctx["port"] = str(port)
    if public_url is not None:
        ctx["public_url"] = public_url
    if supabase_app_schemas is not None:
        ctx["supabase_app_schemas"] = supabase_app_schemas
    return ctx


def _write_secret_env_file(name: str, secret_env: dict[str, str]) -> Path | None:
    """Write a deployment's resolved secrets to a mode-0600 env file.

    Keeps secrets out of the generated unit file and the process argv: systemd
    loads it via ``EnvironmentFile=`` and docker via ``--env-file``. Returns the
    path, or ``None`` (after removing any stale file) when there are no secrets,
    so a service that drops its last secret doesn't leave a dangling file.
    """
    path = secret_env_path(name)
    if not secret_env:
        path.unlink(missing_ok=True)
        return None
    SECRET_ENV_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_ENV_DIR, 0o700)
    # O_TRUNC keeps a pre-existing file's mode, so chmod explicitly afterwards.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for key, value in secret_env.items():
            f.write(f"{key}={value}\n")
    os.chmod(path, 0o600)
    return path


def _resolve_description(config: CastleConfig, spec: DeploymentBase) -> str | None:
    """Get description, falling through to program if referenced."""
    if spec.description:
        return spec.description
    if spec.program and spec.program in config.programs:
        return config.programs[spec.program].description
    return None


def _registry_requires(dep: DeploymentSpec) -> list[dict]:
    """A deployment's `requires` as plain dicts for the registry — carried into the
    mesh payload so peers can draw cross-node consumption."""
    return [
        {"kind": r.kind, "ref": r.ref, "bind": r.bind}
        for r in (getattr(dep, "requires", None) or [])
    ]


def _build_deployed(
    config: CastleConfig, name: str, dep: DeploymentSpec, messages: list[str]
) -> Deployment:
    """Build a runtime Deployment from a DeploymentSpec, dispatched by its manager."""
    description = _resolve_description(config, dep)
    kind = kind_for(dep)
    stack = None
    if dep.program and dep.program in config.programs:
        stack = config.programs[dep.program].stack
    source_dir = _program_source_dir(config, dep.program)

    # Non-process managers (caddy/path/none) have no unit and no run_cmd — the
    # gateway, PATH, or another node is their runtime.
    if isinstance(dep, CaddyDeployment):
        # Serves <program-source>/<root> via the gateway; inherently exposed.
        static_root = str(source_dir / dep.root) if source_dir is not None else None
        return Deployment(
            manager="caddy",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            subdomain=name,
            public=bool(dep.public),
            public_host=(dep.public_host if dep.public else None),
            static_root=static_root,
            managed=False,
            enabled=dep.enabled,
            requires=_registry_requires(dep),
        )
    if isinstance(dep, PathDeployment):
        return Deployment(
            manager="path",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            managed=False,
            enabled=dep.enabled,
            requires=_registry_requires(dep),
        )
    if isinstance(dep, RemoteDeployment):
        return Deployment(
            manager="none",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            base_url=dep.base_url,
            managed=False,
            enabled=dep.enabled,
            requires=_registry_requires(dep),
        )

    # systemd: a supervised process (a service, or a job when scheduled).
    run = dep.run
    # ${data_dir} is keyed by the program the deployment runs, not the deployment
    # name (e.g. job `protonmail-sync` runs program `protonmail` →
    # /data/castle/protonmail). Falls back to the deployment name.
    config_key = dep.program or name

    managed = True
    if dep.manage and dep.manage.systemd and not dep.manage.systemd.enable:
        managed = False

    # `http_exposed` is the HTTP-gateway checkbox (reach != off AND an http port);
    # the subdomain is the deployment name. A raw-TCP service is not http_exposed —
    # it's reachable at <name>.<domain>:<tcp_port> via bind + wildcard DNS.
    expose = dep.http_exposed
    port = None
    health_path = None
    if dep.expose and dep.expose.http:
        port = dep.expose.http.internal.port
        health_path = dep.expose.http.health_path
    tcp_port = dep.tcp_port

    # Env is exactly what's in defaults.env — no hidden convention injection.
    # ${port}/${data_dir}/${name}/${public_url} map the program's own env var
    # names to castle's computed values. Secret-bearing vars split out to a
    # mode-0600 file (never in the unit or argv).
    raw_env = dict(dep.defaults.env) if (dep.defaults and dep.defaults.env) else {}
    # Env generated from `requires` ({kind: deployment, bind: VAR} → target URL).
    # An explicit defaults.env value always wins — a hand-set var is never clobbered.
    for var, url in _requires_env(config, dep).items():
        raw_env.setdefault(var, url)
    public_url = _public_url(config, name, expose, port)
    ctx = _env_context(
        name,
        config_key,
        port,
        config.data_dir,
        public_url,
        _supabase_app_schemas(config),
    )
    # ${tls_*}: paths to castle-materialized cert files for a TLS-material TCP
    # service. The deployment maps them into its own config (mount ${tls_dir} for a
    # container, or reference ${tls_cert}/${tls_key} directly for a native service).
    tls = dep.expose.tcp.tls if (dep.expose and dep.expose.tcp) else None
    if tls and tls.material != TlsMaterial.OFF:
        from castle_core.tls import tls_dir_for

        tls_dir = tls_dir_for(config.data_dir, config_key)
        ctx.update(
            {
                "tls_dir": str(tls_dir),
                "tls_cert": str(tls_dir / "cert.pem"),
                "tls_key": str(tls_dir / "key.pem"),
                "tls_pem": str(tls_dir / "combined.pem"),
                "tls_ca": str(tls_dir / "chain.pem"),
            }
        )
    env, secret_env = resolve_env_split(raw_env, ctx)
    secret_env_file = _write_secret_env_file(name, secret_env)

    # `command` launchers resolve a tool on PATH → ensure it's installed.
    # `python` launchers run in place via `uv run` (below) — no tool venv.
    if run.launcher == "command":
        _ensure_python_tool(config, dep.program, messages)

    run_cmd = _build_run_cmd(
        name,
        run,
        env,
        messages,
        source_dir,
        secret_env_file=secret_env_file,
        placeholders=ctx,
    )
    stop_cmd = _build_stop_cmd(name, run, source_dir)

    # A program that pins a node version (.node-version/.nvmrc/engines) → that node's
    # bin dir on the unit PATH, so a `launcher: node` service runs the program's node
    # (the default tool PATH omits nvm's versioned dirs). Harmless for non-node
    # programs (no pin → no prepend). Fail-soft: a missing pinned version is a warning,
    # not an aborted apply — it surfaces again, loudly, when the build/verb runs.
    path_prepend: list[str] = []
    try:
        node_bin = resolve_node_bin(source_dir)
        if node_bin is not None:
            path_prepend = [str(node_bin)]
    except ToolchainError as e:
        messages.append(f"⚠ {name}: {e}")

    return Deployment(
        manager="systemd",
        launcher=run.launcher,
        run_cmd=run_cmd,
        stop_cmd=stop_cmd,
        env=env,
        path_prepend=path_prepend,
        secret_env_keys=sorted(secret_env),
        description=description,
        kind=kind,
        stack=stack,
        port=port,
        health_path=health_path,
        subdomain=(name if expose else None),
        public=bool(dep.public and expose),
        public_host=(dep.public_host if (dep.public and expose) else None),
        tcp_port=tcp_port,
        schedule=getattr(dep, "schedule", None),
        managed=managed,
        enabled=dep.enabled,
        requires=_registry_requires(dep),
    )


def _python_tool_needs_install(program: str) -> bool:
    """Check if a Python tool's editable install is broken."""
    if not shutil.which(program):
        return True
    tool_dir = Path.home() / ".local" / "share" / "uv" / "tools" / program
    if not tool_dir.exists():
        return True
    for pth_file in tool_dir.glob("lib/python*/site-packages/*.pth"):
        if pth_file.name == "_virtualenv.pth":
            continue
        try:
            target = pth_file.read_text().strip()
        except OSError:
            continue
        if not target or target.startswith("import "):
            continue
        if not Path(target).exists():
            return True
    return False


def _program_source_dir(config: CastleConfig, program: str | None) -> Path | None:
    """The absolute source dir of a referenced program, if any.

    `load_config` has already resolved `source` to an absolute path (repo: and
    relative forms included), so this is a plain lookup."""
    if program and program in config.programs:
        src = config.programs[program].source
        if src:
            return Path(src)
    return None


def _ensure_python_tool(
    config: CastleConfig, program: str | None, messages: list[str]
) -> None:
    """Ensure a Python program's editable install is current.

    Only the `command` runner needs this — it resolves a tool on PATH. The
    `python` runner runs in place via `uv run` and never touches a tool venv."""
    if not program or program not in config.programs:
        return
    comp = config.programs[program]
    if not comp.source or not comp.stack or not comp.stack.startswith("python"):
        return
    source_dir = Path(comp.source)
    if not source_dir.is_dir():
        messages.append(f"Warning: source not found: {source_dir}")
        return
    if not _python_tool_needs_install(program):
        return
    pkg_spec = str(source_dir)
    if comp.install_extras:
        pkg_spec += "[" + ",".join(comp.install_extras) + "]"
    messages.append(f"Installing {program} from {source_dir}...")
    result = subprocess.run(
        ["uv", "tool", "install", "--editable", pkg_spec, "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        messages.append(
            f"Error: {program} install failed:\n{result.stdout}{result.stderr}"
        )
    else:
        messages.append(f"Installed {program}")


def _subst(value: str, placeholders: dict[str, str] | None) -> str:
    """Expand ``${key}`` in a run-spec string field from castle's computed values
    (``${uid}``/``${gid}``/``${data_dir}``/``${tls_dir}``/…), via the one shared
    ``${...}`` resolver (:func:`resolve_placeholders`). Unknown refs pass through
    unchanged (secrets never belong in argv — they go via --env-file); write
    ``$${key}`` to pass a literal ``${key}`` to a container's own shell/env."""
    return resolve_placeholders(value, placeholders)


def _build_run_cmd(
    name: str,
    run: object,
    env: dict[str, str],
    messages: list[str],
    source_dir: Path | None = None,
    secret_env_file: Path | None = None,
    placeholders: dict[str, str] | None = None,
) -> list[str]:
    """Build a run command list from a LaunchSpec (a systemd deployment's `run`).

    ``env`` holds plain (non-secret) vars only; ``secret_env_file`` is the
    mode-0600 file holding the deployment's secrets. For container runners the
    secrets are passed via ``--env-file`` (keeping them out of the argv);
    systemd-launched runners get them via ``EnvironmentFile=`` on the unit, so
    ``secret_env_file`` is unused here for those.
    """
    match run.launcher:  # type: ignore[union-attr]
        case "python":
            # Run the program in place from its own project venv via `uv run`,
            # which syncs the env to the lockfile before launching. One venv per
            # program (no separate tool venv); restart picks up both code and
            # dependency changes. Falls back to a PATH lookup only when there's no
            # resolvable source (a service that declares run.program without a
            # catalog program).
            if source_dir and source_dir.is_dir():
                uv = shutil.which("uv") or "uv"
                cmd = [uv, "run", "--project", str(source_dir), "--no-dev", run.program]  # type: ignore[union-attr]
            else:
                resolved = shutil.which(run.program)  # type: ignore[union-attr]
                if not resolved:
                    messages.append(
                        f"Warning: '{run.program}' has no source dir and is not on "  # type: ignore[union-attr]
                        f"PATH. Declare a program source, or install it."
                    )
                cmd = [resolved or run.program]  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case "command":
            cmd = list(run.argv)  # type: ignore[union-attr]
            resolved = shutil.which(cmd[0])
            if resolved:
                cmd[0] = resolved
            return cmd
        case "container":
            runtime = shutil.which("docker") or shutil.which("podman") or "docker"
            # Container name derives from the SERVICE name (matches the systemd unit),
            # not the image name — so `castle-<service>` is stable and collision-free.
            cmd = [runtime, "run", "--rm", f"--name=castle-{name}"]
            if run.user:  # type: ignore[union-attr]
                # Run as the invoking user (uid uniformity → bind-mounted
                # certs/data/secrets readable with no chown). ${uid}/${gid} expand
                # to the castle process's own ids.
                cmd.extend(["--user", _subst(run.user, placeholders)])  # type: ignore[union-attr]
            for tp in run.tmpfs:  # type: ignore[union-attr]
                cmd.extend(["--tmpfs", _subst(tp, placeholders)])
            for container_port, host_port in run.ports.items():  # type: ignore[union-attr]
                cmd.extend(["-p", f"{host_port}:{container_port}"])
            for vol in run.volumes:  # type: ignore[union-attr]
                cmd.extend(["-v", _subst(vol, placeholders)])
            for key, val in run.env.items():  # type: ignore[union-attr]
                cmd.extend(["-e", f"{key}={_subst(val, placeholders)}"])
            # env is plain-only; secrets go via --env-file so they never hit argv.
            for key, val in env.items():
                cmd.extend(["-e", f"{key}={val}"])
            if secret_env_file is not None:
                cmd.extend(["--env-file", str(secret_env_file)])
            if run.workdir:  # type: ignore[union-attr]
                cmd.extend(["-w", _subst(run.workdir, placeholders)])  # type: ignore[union-attr]
            cmd.append(run.image)  # type: ignore[union-attr]
            if run.command:  # type: ignore[union-attr]
                cmd.extend(_subst(c, placeholders) for c in run.command)  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(_subst(a, placeholders) for a in run.args)  # type: ignore[union-attr]
            return cmd
        case "compose":
            # A whole docker-compose stack supervised as one unit. `up` runs
            # attached (no -d) so systemd Type=simple owns the lifecycle; teardown
            # is a generated ExecStop (`down`, see _build_stop_cmd). Secrets/env
            # reach compose via the unit's Environment=/EnvironmentFile= (compose
            # interpolates from the process env), not argv — so nothing here.
            return [*_compose_base(name, run, source_dir), "up"]
        case "node":
            # Like the python runner bakes `--project <source>` into `uv run`, the
            # node runner bakes `--dir <source>` so the package manager runs the
            # script in the program's source dir — the systemd unit carries no
            # WorkingDirectory, so a bare `pnpm run` would otherwise execute in the
            # service's (wrong) cwd. Resolve the package manager to an absolute path.
            pm = shutil.which(run.package_manager) or run.package_manager  # type: ignore[union-attr]
            cmd = [pm]
            if source_dir and source_dir.is_dir():
                cmd.extend(["--dir", str(source_dir)])
            cmd.extend(["run", run.script])  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case _:
            raise ValueError(f"Unsupported launcher: {run.launcher}")  # type: ignore[union-attr]


def _compose_base(name: str, run: object, source_dir: Path | None) -> list[str]:
    """The shared ``docker compose -p <project> -f <file>`` prefix for a stack.

    The compose file is resolved against the program source (like the node runner
    uses ``--dir``) so the unit — which carries no WorkingDirectory — finds it. The
    project name defaults to the unit name so a stack's containers/networks are
    namespaced and collision-free.
    """
    runtime = shutil.which("docker") or shutil.which("podman") or "docker"
    project = run.project_name or f"castle-{name}"  # type: ignore[union-attr]
    compose_file = Path(run.file)  # type: ignore[union-attr]
    if not compose_file.is_absolute() and source_dir is not None:
        compose_file = source_dir / compose_file
    return [runtime, "compose", "-p", project, "-f", str(compose_file)]


def _build_stop_cmd(name: str, run: object, source_dir: Path | None) -> list[str]:
    """The ExecStop teardown command for a runner, or [] if a plain SIGTERM suffices.

    Compose stacks need an explicit ``down`` so networks/anonymous volumes are
    reclaimed rather than left dangling when the unit stops.
    """
    if run.launcher == "compose":  # type: ignore[union-attr]
        return [*_compose_base(name, run, source_dir), "down"]
    return []


def _format_deployed(name: str, deployed: Deployment) -> str:
    """Format deployment summary for a component."""
    parts = [name]
    if deployed.port:
        parts.append(f"port={deployed.port}")
    if deployed.schedule:
        parts.append(f"schedule={deployed.schedule}")
    if deployed.subdomain:
        parts.append(f"subdomain={deployed.subdomain}")
    return " ".join(parts)


def _desired_unit_files(registry: NodeRegistry) -> set[str]:
    """Exact set of unit filenames that should exist on disk for this registry."""
    files: set[str] = set()
    for _key, deployed in registry.deployed.items():
        if not deployed.managed:
            continue
        files.add(unit_name(deployed.name, deployed.kind))
        if deployed.schedule:
            files.add(timer_name(deployed.name))
    return files


def _teardown_unit(unit_file: str, messages: list[str]) -> None:
    """Stop, disable, and unlink a systemd unit file. Caller batches daemon-reload."""
    path = SYSTEMD_USER_DIR / unit_file
    if not path.exists():
        return
    subprocess.run(["systemctl", "--user", "stop", unit_file], check=False)
    subprocess.run(["systemctl", "--user", "disable", unit_file], check=False)
    path.unlink()
    messages.append(f"Pruned orphan unit: {unit_file}")
    # Remove the matching secret env file (only services have one; not timers).
    if unit_file.endswith(".service"):
        (SECRET_ENV_DIR / f"{unit_file}.env").unlink(missing_ok=True)


def _prune_orphans(registry: NodeRegistry, messages: list[str]) -> None:
    """Remove castle-* units no longer backed by a managed registry entry.

    The `castle-` prefix is the ownership namespace: any castle-*.service/.timer on
    disk that isn't in the desired set is an orphan (a removed/unmanaged/unscheduled
    component) and is torn down. Only call on a FULL deploy — the desired set must
    reflect the whole registry, not a single --target.
    """
    desired = _desired_unit_files(registry)
    if not SYSTEMD_USER_DIR.is_dir():
        return
    for pattern in ("castle-*.service", "castle-*.timer"):
        for path in sorted(SYSTEMD_USER_DIR.glob(pattern)):
            if path.name not in desired:
                _teardown_unit(path.name, messages)


def _render_unit_files(
    config: CastleConfig, name: str, deployed: Deployment
) -> dict[str, str]:
    """The exact unit files `deploy` would write for a deployment: {filename: content}.

    Empty for a non-systemd-managed deployment (caddy/path/none have no unit). The
    single source of truth for unit bytes — used both to write units and to predict
    restart-on-change in `apply`/`--plan`, so the prediction can never drift from
    what actually gets written.
    """
    if not deployed.managed:
        return {}
    systemd_spec = None
    dep = config.deployment(deployed.kind, name)
    manage = getattr(dep, "manage", None)
    if manage and manage.systemd:
        systemd_spec = manage.systemd

    files = {
        unit_name(name, deployed.kind): generate_unit_from_deployed(
            name, deployed, systemd_spec, env_file=unit_env_file(deployed, name)
        )
    }
    if deployed.schedule:
        files[timer_name(name)] = generate_timer(
            name, schedule=deployed.schedule, description=deployed.description
        )
    return files


def _generate_systemd_units(config: CastleConfig, registry: NodeRegistry) -> None:
    """Generate systemd units from the registry."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    for _key, deployed in registry.deployed.items():
        for fname, content in _render_unit_files(
            config, deployed.name, deployed
        ).items():
            (SYSTEMD_USER_DIR / fname).write_text(content)
