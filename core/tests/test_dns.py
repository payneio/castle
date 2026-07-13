"""Tests for multi-zone public DNS (Cloudflare CNAME) reconciliation."""

from __future__ import annotations

import castle_core.generators.dns as dns
from castle_core.generators.dns import _zone_for, reconcile_public_dns

TID = "tid-abc"
TARGET = f"{TID}.cfargotunnel.com"

ZONES = [
    {"id": "z_payne", "name": "payne.io"},
    {"id": "z_ex", "name": "example.org"},
]


class _FakeCloudflare:
    """A minimal fake of the Cloudflare API used by reconcile_public_dns.

    ``records`` maps zone_id -> {name: (record_id, content)}. Records POST/DELETE
    calls so tests can assert exactly what castle created/removed.
    """

    def __init__(self, records: dict[str, dict[str, tuple[str, str]]]):
        self.records = records
        self.created: list[tuple[str, str]] = []  # (zone_id, name)
        self.deleted: list[tuple[str, str]] = []  # (zone_id, record_id)
        self._n = 0

    def api(self, token: str, method: str, path: str, body: dict | None = None) -> dict:
        if method == "GET" and path.startswith("/zones?"):
            return {"result": ZONES}
        if method == "GET" and "/dns_records" in path:
            zone_id = path.split("/zones/")[1].split("/")[0]
            recs = self.records.get(zone_id, {})
            return {
                "result": [
                    {"id": rid, "name": name, "content": content, "type": "CNAME"}
                    for name, (rid, content) in recs.items()
                ]
            }
        if method == "POST":
            zone_id = path.split("/zones/")[1].split("/")[0]
            assert body is not None
            self.created.append((zone_id, body["name"]))
            return {"result": {"id": f"new{self._n}"}}
        if method == "DELETE":
            zone_id = path.split("/zones/")[1].split("/")[0]
            rid = path.rsplit("/", 1)[1]
            self.deleted.append((zone_id, rid))
            return {"result": {"id": rid}}
        raise AssertionError(f"unexpected call {method} {path}")


def _run(fake: _FakeCloudflare, desired: list[str], monkeypatch) -> list[str]:
    monkeypatch.setattr(dns, "_api", fake.api)
    messages: list[str] = []
    ok = reconcile_public_dns(TID, desired, messages, token="tok")
    assert ok is True
    return messages


def test_longest_suffix_routes_host_to_its_zone() -> None:
    assert _zone_for("payne.io", ZONES)["id"] == "z_payne"       # apex
    assert _zone_for("api.payne.io", ZONES)["id"] == "z_payne"   # subdomain
    assert _zone_for("app.example.org", ZONES)["id"] == "z_ex"
    assert _zone_for("nope.other.net", ZONES) is None            # no visible zone


def test_creates_apex_and_subdomain_in_correct_zones(monkeypatch) -> None:
    fake = _FakeCloudflare(records={"z_payne": {}, "z_ex": {}})
    _run(fake, ["payne.io", "app.example.org"], monkeypatch)
    assert set(fake.created) == {("z_payne", "payne.io"), ("z_ex", "app.example.org")}
    assert fake.deleted == []


def test_deletes_managed_cname_no_longer_desired(monkeypatch) -> None:
    # z_payne has a stale castle-managed CNAME + a hand-managed one pointing elsewhere.
    fake = _FakeCloudflare(records={
        "z_payne": {
            "payne.io": ("r1", TARGET),          # castle-managed, still desired
            "old.payne.io": ("r2", TARGET),      # castle-managed, now stale → delete
            "keep.payne.io": ("r3", "other.example.com"),  # NOT ours → never touched
        },
        "z_ex": {},
    })
    _run(fake, ["payne.io"], monkeypatch)
    assert fake.created == []
    assert fake.deleted == [("z_payne", "r2")]  # only the stale managed one


def test_empty_desired_cleans_all_managed(monkeypatch) -> None:
    fake = _FakeCloudflare(records={
        "z_payne": {"payne.io": ("r1", TARGET)},
        "z_ex": {"a.example.org": ("r2", TARGET)},
    })
    _run(fake, [], monkeypatch)
    assert set(fake.deleted) == {("z_payne", "r1"), ("z_ex", "r2")}


def test_no_token_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(dns, "public_dns_token", lambda: None)
    assert reconcile_public_dns(TID, ["payne.io"], [], token=None) is False


def test_unresolvable_host_warns_but_still_reconciles_others(monkeypatch) -> None:
    fake = _FakeCloudflare(records={"z_payne": {}, "z_ex": {}})
    msgs = _run(fake, ["payne.io", "x.unknown.net"], monkeypatch)
    assert fake.created == [("z_payne", "payne.io")]
    assert any("unknown.net" in m for m in msgs)
