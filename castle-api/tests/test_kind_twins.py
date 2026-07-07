"""A tool, a service, and a job may share a name — kind-scoped endpoints must
address (and mutate) exactly one twin.

These guard the collision case the per-kind identity refactor enables: a
`backup` service + job + tool coexisting. The risk is a save/delete against one
kind bleeding into a same-named twin of another kind. We assert against the
on-disk config (load_config) so we're testing the persisted invariant, not a
response echo.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from castle_core.config import load_config

# Minimal, valid specs for each kind — all named "backup", all referencing the
# same program. Only the service is HTTP-exposed (none claims a subdomain here),
# so the trio passes subdomain-uniqueness validation.
_SVC = {
    "program": "backup",
    "manager": "systemd",
    "run": {"launcher": "python", "program": "backup"},
    "manage": {"systemd": {}},
}
_JOB = {
    "program": "backup",
    "manager": "systemd",
    "run": {"launcher": "command", "argv": ["backup"]},
    "schedule": "0 3 * * *",
}
_TOOL = {"program": "backup", "manager": "path"}


def _put(client: TestClient, section: str, name: str, cfg: dict) -> None:
    r = client.put(f"/config/{section}/{name}", json={"config": cfg})
    assert r.status_code == 200, r.text


class TestKindScopedTwins:
    def test_same_name_across_kinds_coexist(
        self, client: TestClient, castle_root: Path
    ) -> None:
        """Creating a service, job, and tool all named `backup` yields three
        distinct deployments — one per kind, none overwriting another."""
        _put(client, "services", "backup", _SVC)
        _put(client, "jobs", "backup", _JOB)
        _put(client, "tools", "backup", _TOOL)

        cfg = load_config(castle_root)
        assert "backup" in cfg.services
        assert "backup" in cfg.jobs
        assert "backup" in cfg.tools

    def test_detail_endpoints_resolve_the_right_twin(
        self, client: TestClient, castle_root: Path
    ) -> None:
        """`/services/backup` and `/jobs/backup` each return their own kind, not
        whichever twin happens to sort first."""
        _put(client, "services", "backup", _SVC)
        _put(client, "jobs", "backup", _JOB)

        svc = client.get("/services/backup").json()
        job = client.get("/jobs/backup").json()
        assert svc["kind"] == "service"
        # Each endpoint returns its own twin: the job carries the schedule, the
        # service does not — so neither resolved to the other.
        assert job["manifest"].get("schedule") == "0 3 * * *"
        assert "schedule" not in svc["manifest"]

    def test_kind_scoped_save_does_not_touch_the_twin(
        self, client: TestClient, castle_root: Path
    ) -> None:
        """A partial patch to the *service* backup must leave the *job* backup
        (and its schedule) untouched — the wrong-twin bleed this refactor closes."""
        _put(client, "services", "backup", _SVC)
        _put(client, "jobs", "backup", _JOB)

        _put(client, "services", "backup", {"reach": "off"})

        cfg = load_config(castle_root)
        assert cfg.jobs["backup"].schedule == "0 3 * * *"  # job untouched
        assert "backup" in cfg.services  # service still there

    def test_kind_scoped_delete_removes_only_that_twin(
        self, client: TestClient, castle_root: Path
    ) -> None:
        """Deleting `/config/tools/backup` drops only the tool; the service and
        job twins survive."""
        _put(client, "services", "backup", _SVC)
        _put(client, "jobs", "backup", _JOB)
        _put(client, "tools", "backup", _TOOL)

        r = client.delete("/config/tools/backup")
        assert r.status_code == 200, r.text

        cfg = load_config(castle_root)
        assert "backup" not in cfg.tools  # tool gone
        assert "backup" in cfg.services  # twins survive
        assert "backup" in cfg.jobs
