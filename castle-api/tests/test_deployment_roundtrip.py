"""Edit-safety tests for the deployment detail + save endpoints.

These guard the regression that broke astro (and postgres): the detail endpoint
served the *runtime view* (no reach/program/root/expose) for a deployed deployment,
so the dashboard edit form round-tripped a lossy manifest and stripped spec-only
fields on save. The fixtures already have `test-svc` deployed AND defined in
castle.yaml (with legacy `proxy: true` → `reach: internal`) — exactly that case.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestDeploymentEditSafety:
    def test_detail_serves_editable_spec_not_runtime(self, client: TestClient) -> None:
        """A deployed deployment that's in castle.yaml serves its EDITABLE SPEC —
        the shape the edit form consumes (launcher nested under `run`, plus
        reach/expose) — not the flat runtime view (`run_cmd`, top-level launcher)."""
        m = client.get("/deployments/test-svc").json()["manifest"]
        assert m["run"]["launcher"] == "python"  # spec shape (nested)
        assert "run_cmd" not in m  # runtime-only key absent
        assert m.get("reach") == "internal"  # normalized from proxy:true
        assert m["expose"]["http"]["internal"]["port"] == 19000

    def test_save_roundtrip_preserves_spec_fields(self, client: TestClient) -> None:
        """GET a deployment's manifest → PUT it back unchanged → GET again: no
        spec field may be lost. This is the exact round-trip the dashboard does on
        an edit, and the exact thing that dropped astro's program/root."""
        before = client.get("/deployments/test-svc").json()["manifest"]
        resp = client.put("/config/deployments/test-svc", json={"config": before})
        assert resp.status_code == 200, resp.text
        after = client.get("/deployments/test-svc").json()["manifest"]
        for key in ("reach", "expose", "run", "program"):
            assert after.get(key) == before.get(key), f"{key} lost on save round-trip"

    def test_partial_patch_preserves_untouched_fields(self, client: TestClient) -> None:
        """PATCH semantics: sending ONLY the changed field must not drop the rest.
        This is what makes the astro-class regression structurally impossible —
        even a client that sends a lossy payload can't nuke fields it omitted."""
        before = client.get("/deployments/test-svc").json()["manifest"]
        resp = client.put(
            "/config/deployments/test-svc", json={"config": {"reach": "off"}}
        )
        assert resp.status_code == 200, resp.text
        after = client.get("/deployments/test-svc").json()["manifest"]
        assert after["reach"] == "off"  # the change applied
        assert after["program"] == before["program"]  # untouched → preserved
        assert after["run"] == before["run"]
        assert after["expose"] == before["expose"]

    def test_explicit_null_clears_a_field(self, client: TestClient) -> None:
        """An explicit null clears a field — so a form can still *remove* exposure
        under merge semantics (omit = preserve, null = clear). Removing the port
        goes with reach: off (a port-only process), which is what ServiceFields
        sends when the port is cleared."""
        resp = client.put(
            "/config/deployments/test-svc",
            json={"config": {"expose": None, "reach": "off"}},
        )
        assert resp.status_code == 200, resp.text
        after = client.get("/deployments/test-svc").json()["manifest"]
        assert after.get("expose") is None  # cleared
        assert after["reach"] == "off"
        assert after["program"] == "test-svc-comp"  # rest preserved


class TestProgramEditSafety:
    def test_program_partial_patch_preserves(self, client: TestClient) -> None:
        """save_program is the same footgun: a partial edit must not drop
        source/commands. Send only a description; the rest survives."""
        resp = client.put(
            "/config/programs/wired-in",
            json={"config": {"description": "renamed"}},
        )
        assert resp.status_code == 200, resp.text
        m = client.get("/programs/wired-in").json()["manifest"]
        assert m["description"] == "renamed"  # change applied
        assert m["source"].endswith("wired-in")  # source preserved
        assert m["commands"]["lint"] == [["make", "lint"]]  # commands preserved
