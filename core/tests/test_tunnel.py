"""Tests for cloudflared tunnel ingress generation."""

from __future__ import annotations

import yaml

from castle_core.generators.tunnel import (
    generate_tunnel_config,
    public_hostnames,
)
from castle_core.registry import Deployment, NodeConfig, NodeRegistry


def _registry(
    *,
    tunnel_id: str | None = "tid-123",
    public_domain: str | None = "pub.payne.io",
    gateway_domain: str | None = "civil.payne.io",
    deployed: dict[str, Deployment] | None = None,
) -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(
            hostname="civil",
            gateway_tls="acme",
            gateway_domain=gateway_domain,
            public_domain=public_domain,
            tunnel_id=tunnel_id,
        ),
        deployed=deployed
        or {
            "app": Deployment(manager="systemd", launcher="python", run_cmd=["x"], port=9001,
                              subdomain="app", public=True),
            "private": Deployment(manager="systemd", launcher="python", run_cmd=["y"], port=9002,
                                 subdomain="private", public=False),
        },
    )


def test_public_service_maps_public_zone_to_internal_host() -> None:
    cfg = yaml.safe_load(generate_tunnel_config(_registry()))
    assert cfg["tunnel"] == "tid-123"
    rules = {r.get("hostname"): r for r in cfg["ingress"] if "hostname" in r}
    # only the public service is mapped
    assert set(rules) == {"app.pub.payne.io"}
    r = rules["app.pub.payne.io"]
    assert r["service"] == "https://localhost:443"
    # public zone → internal host (Host + SNI rewritten so Caddy routes + cert validates)
    assert r["originRequest"]["httpHostHeader"] == "app.civil.payne.io"
    assert r["originRequest"]["originServerName"] == "app.civil.payne.io"


def test_terminal_catch_all_present() -> None:
    cfg = yaml.safe_load(generate_tunnel_config(_registry()))
    assert cfg["ingress"][-1] == {"service": "http_status:404"}


def test_private_service_not_in_public_dns() -> None:
    assert public_hostnames(_registry()) == ["app.pub.payne.io"]


def test_none_when_no_public_services() -> None:
    only_private = {
        "x": Deployment(manager="systemd", launcher="python", run_cmd=["x"], subdomain="x", public=False)
    }
    assert generate_tunnel_config(_registry(deployed=only_private)) is None


def test_none_when_tunnel_unconfigured() -> None:
    assert generate_tunnel_config(_registry(tunnel_id=None)) is None
    assert generate_tunnel_config(_registry(public_domain=None)) is None


def test_public_static_frontend_gets_ingress() -> None:
    # A `static` (frontend) service can be public too — the toggle composes for
    # any exposed deployment, process-backed or not.
    reg = _registry(deployed={
        "guestbook": Deployment(manager="caddy", run_cmd=[], subdomain="guestbook",
                               static_root="/data/repos/guestbook/public", public=True),
    })
    hosts = {r["hostname"] for r in yaml.safe_load(generate_tunnel_config(reg))["ingress"]
             if "hostname" in r}
    assert hosts == {"guestbook.pub.payne.io"}


def test_public_host_override_used_as_ingress_hostname() -> None:
    # An apex `public_host` overrides <sub>.<public_domain> for the public name,
    # but the origin still bridges to the internal <sub>.<gateway_domain> host.
    reg = _registry(deployed={
        "payne-io": Deployment(manager="caddy", run_cmd=[], subdomain="payne-io",
                              static_root="/data/repos/payne-io/public", public=True,
                              public_host="payne.io"),
    })
    cfg = yaml.safe_load(generate_tunnel_config(reg))
    rules = {r["hostname"]: r for r in cfg["ingress"] if "hostname" in r}
    assert set(rules) == {"payne.io"}
    assert rules["payne.io"]["originRequest"]["httpHostHeader"] == "payne-io.civil.payne.io"
    assert public_hostnames(reg) == ["payne.io"]


def test_public_host_default_and_override_coexist() -> None:
    reg = _registry(deployed={
        "app": Deployment(manager="systemd", launcher="python", run_cmd=["x"], port=9001,
                          subdomain="app", public=True),
        "payne-io": Deployment(manager="caddy", run_cmd=[], subdomain="payne-io",
                              static_root="/d/public", public=True, public_host="payne.io"),
    })
    assert set(public_hostnames(reg)) == {"app.pub.payne.io", "payne.io"}


def test_public_host_works_without_default_public_domain() -> None:
    # A deployment with its own public_host publishes even if the node has no
    # default public_domain; the plain public service (no override) is skipped.
    reg = _registry(public_domain=None, deployed={
        "app": Deployment(manager="systemd", launcher="python", run_cmd=["x"], port=9001,
                          subdomain="app", public=True),
        "payne-io": Deployment(manager="caddy", run_cmd=[], subdomain="payne-io",
                              static_root="/d/public", public=True, public_host="payne.io"),
    })
    assert public_hostnames(reg) == ["payne.io"]
    cfg = yaml.safe_load(generate_tunnel_config(reg))
    hosts = {r["hostname"] for r in cfg["ingress"] if "hostname" in r}
    assert hosts == {"payne.io"}
