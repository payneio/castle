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


def suggest_consumption(config: CastleConfig) -> list[Suggestion]:
    """Undeclared consumption suggestions, derived from env endpoint values.

    For each deployment, scan its ``defaults.env`` values for ``host:port`` (or a
    URL). When the port resolves to a *local* provider's socket and the consumer
    doesn't already declare it, propose the edge. Deduped per (consumer, provider)."""
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
        for var, val in env.items():
            for m in _HOSTPORT.finditer(str(val)):
                host = m.group("host")
                port = int(m.group("port"))
                prov = port_provider.get(port)
                if not prov:
                    continue
                pname, proto = prov
                # Only resolve when the value points at a local host (this node's
                # providers) or names the provider directly — avoids matching a
                # coincidental external host that happens to share a port number.
                if host not in _LOCAL_HOSTS and host != pname:
                    continue
                if pname == name or pname in declared or pname in proposed:
                    continue
                proposed.add(pname)
                out.append(Suggestion(name, pname, var, f"{host}:{port}", proto))
    return out
