"""Consumption audit — *suggests* undeclared ``requires`` by matching a
deployment's env endpoint values against known provider sockets.

This is the one place castle looks at env → dependency, and it does so **only to
propose a declaration the user confirms** — never to write, and never to feed the
graph or ``functional?``. The relationship graph stays strictly declaration-derived
(see docs/relationships.md, "Env is derived *from* requires, never scraped *into*
it"); this module is an explicit, opt-in lint that sits *on top* of it. A suggestion
is accepted by writing a real ``requires`` (a declaration), at which point it stops
being a suggestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from castle_core.config import CastleConfig
from castle_core.relations import build_model

# Hosts that mean "a provider on this node" — a port match against them is a strong
# signal (ports are unique per host). 172.17.0.1 is the docker bridge to the host.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "172.17.0.1"}

# scheme://host:port  OR  host:port  — anywhere inside an env value.
_HOSTPORT = re.compile(r"(?:(?P<scheme>[a-z][\w+.-]*)://)?(?P<host>[\w.-]+):(?P<port>\d{2,5})")


@dataclass
class Suggestion:
    consumer: str  # the deployment whose env references the endpoint
    provider: str  # the provider deployment the port resolves to
    env_var: str  # the env var that revealed it
    endpoint: str  # host:port as seen in the value
    protocol: str  # the provider's socket protocol


def _resolve(
    host: str,
    port: int,
    *,
    consumer: str,
    port_provider: dict[int, tuple[str, str]],
    declared: set[str],
    proposed: set[str],
    env_var: str,
    out: list[Suggestion],
) -> None:
    """Resolve a (host, port) to a provider and record a suggestion if it's a new,
    undeclared, local match. Only resolve local hosts (this node's providers) or a
    host that names the provider — avoids matching a coincidental external host that
    happens to share a port number."""
    prov = port_provider.get(port)
    if not prov:
        return
    pname, proto = prov
    if host not in _LOCAL_HOSTS and host != pname:
        return
    if pname == consumer or pname in declared or pname in proposed:
        return
    proposed.add(pname)
    out.append(Suggestion(consumer, pname, env_var, f"{host}:{port}", proto))


def suggest_consumption(config: CastleConfig) -> list[Suggestion]:
    """Undeclared consumption suggestions, derived from env endpoint values.

    Two shapes are recognized in a deployment's ``defaults.env``:
    (a) ``host:port`` inside a single value (a URL, a ``DATABASE_URL``); and
    (b) a split ``X_HOST`` + ``X_PORT`` pair (e.g. ``CASTLE_API_MQTT_HOST`` +
    ``CASTLE_API_MQTT_PORT``). When the port resolves to a *local* provider's socket
    and the consumer doesn't already declare it, propose the edge — deduped per
    (consumer, provider). A bare ``*_PORT`` with no ``*_HOST`` is ignored: without an
    explicit host it can't be told apart from the deployment's own listen port."""
    model = build_model(config, check=False)
    # port -> (provider name, protocol); ports are unique per host, so a port match
    # against a local host is a confident resolution.
    port_provider: dict[int, tuple[str, str]] = {}
    for n in model.nodes:
        for ep in n.endpoints:
            port_provider.setdefault(ep.port, (n.name, ep.protocol))

    out: list[Suggestion] = []
    for _kind, name, dep in config.all_deployments():
        env = dict(dep.defaults.env) if (dep.defaults and dep.defaults.env) else {}
        declared = {r.ref for r in getattr(dep, "requires", [])}
        proposed: set[str] = set()

        def resolve(host: str, port: int, env_var: str) -> None:
            _resolve(
                host,
                port,
                consumer=name,
                port_provider=port_provider,
                declared=declared,
                proposed=proposed,
                env_var=env_var,
                out=out,
            )

        # (a) host:port inside a single value.
        for var, val in env.items():
            for m in _HOSTPORT.finditer(str(val)):
                resolve(m.group("host"), int(m.group("port")), var)
        # (b) split X_HOST + X_PORT pair.
        for var, val in env.items():
            if not var.endswith("_HOST"):
                continue
            pvar = var[:-5] + "_PORT"  # X_HOST -> X_PORT
            if pvar not in env:
                continue
            try:
                port = int(str(env[pvar]).strip())
            except ValueError:
                continue
            resolve(str(val).strip(), port, f"{var}+{pvar}")
    return out
