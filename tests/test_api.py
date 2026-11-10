import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from app import database
from app.main import app
from app.services import ENTITIES, KPI_ROWS, InvestigationService

client=TestClient(app)

def headers(role="alarm_management", customer="CUST-A"):
    return {"X-Demo-Role":role,"X-Customer-ID":customer}


@pytest.fixture(autouse=True)
def reset_persistent_state(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test-network-intelligence.sqlite3")
    database.initialize(KPI_ROWS, ENTITIES)
    yield


def test_health():
    assert client.get("/health").json()["status"]=="ok"

def test_topology_returns_shared_transport():
    r=client.get("/v1/topology/CELL-PUN-101?depth=2",headers=headers())
    assert r.status_code==200
    assert "TX-PUN-01" in [n["id"] for n in r.json()["nodes"]]

def test_tenant_isolation_hides_other_customer_entity():
    r=client.get("/v1/topology/CELL-MUM-201",headers=headers())
    assert r.status_code==404


def test_five_customer_contexts_cannot_cross_read_investigations_or_kpis():
    created = client.post("/v1/investigations",headers=headers(customer="CUST-A"),
                          json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]

    for customer_id in ("CUST-A", "CUST-B", "CUST-C", "CUST-D", "CUST-E"):
        expected = 200 if customer_id == "CUST-A" else 404
        investigation = client.get(
            f"/v1/investigations/{investigation_id}/status",
            headers=headers(customer=customer_id),
        )
        pune_kpis = client.get("/v1/kpis/CELL-PUN-101",headers=headers(customer=customer_id))
        assert investigation.status_code == expected
        assert pune_kpis.status_code == expected

    for customer_id in ("CUST-A", "CUST-C", "CUST-D", "CUST-E"):
        assert client.get("/v1/kpis/CELL-MUM-201",headers=headers(customer=customer_id)).status_code == 404
    assert client.get("/v1/kpis/CELL-MUM-201",headers=headers(customer="CUST-B")).status_code == 200


def test_unknown_role_rejected():
    r=client.get("/v1/kpis/CELL-PUN-101",headers=headers("unknown"))
    assert r.status_code==401

def test_performance_role_cannot_propose_change():
    r=client.post("/v1/change-proposals",headers=headers("performance_analysis"),
                  json={"target_id":"NODE-ERIC-01","action":"restart","rationale":"Restart after validation"})
    assert r.status_code==403


def test_alarm_management_cannot_propose_change():
    response = client.post("/v1/change-proposals",headers=headers("alarm_management"),
                           json={"target_id":"NODE-ERIC-01","action":"restart",
                                 "rationale":"Restart only after review"})
    assert response.status_code == 403

def test_change_planner_proposal_requires_human_approval():
    r=client.post("/v1/change-proposals",headers=headers("change_planning"),
                  json={"target_id":"NODE-ERIC-01","action":"restart","rationale":"Restart after impact review"})
    assert r.status_code==200
    assert r.json()["status"]=="PENDING_HUMAN_APPROVAL"
    assert r.json()["executed"] is False

def test_investigation_marks_provisional_evidence():
    r=client.post("/v1/investigations",headers=headers(),
                  json={"affected_cells":["CELL-PUN-101","CELL-PUN-102"]})
    assert r.status_code==200
    assert r.json()["status"] == "RECEIVED"
    assert r.json()["completeness"] == "UNAVAILABLE"
    assert r.json()["action_executed"] is False
    status = client.get(f"/v1/investigations/{r.json()['investigation_id']}/status",headers=headers())
    assert status.json()["status"] == "PARTIAL_RESULT"
    assert status.json()["completeness"] == "PARTIAL"


def test_investigation_creation_contract_and_unique_ids():
    payload = {"affected_cells": ["CELL-PUN-101"]}
    first = client.post("/v1/investigations",headers=headers(),json=payload)
    second = client.post("/v1/investigations",headers=headers(),json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_record = first.json()
    second_record = second.json()
    assert first_record["investigation_id"] != second_record["investigation_id"]
    assert first_record["customer_id"] == "CUST-A"
    assert first_record["affected_cells"] == payload["affected_cells"]
    assert first_record["status"] == "RECEIVED"
    assert first_record["created_at"]
    assert first_record["updated_at"]
    processed = client.get(f"/v1/investigations/{first_record['investigation_id']}/status",headers=headers()).json()
    assert processed["status"] == "PARTIAL_RESULT"
    assert processed["evidence_completeness"] == "PARTIAL"
    assert processed["topology_snapshot_id"] == "inv-20261110-1000"
    assert processed["recommendations"]
    assert processed["findings"][0]["evidence_status"] == "PROVISIONAL_KPI"


def test_investigation_rejects_invalid_requests():
    empty_cells = client.post("/v1/investigations",headers=headers(),json={"affected_cells": []})
    unknown_cell = client.post("/v1/investigations",headers=headers(),json={"affected_cells": ["UNKNOWN-CELL"]})

    assert empty_cells.status_code == 422
    assert unknown_cell.status_code == 404


def test_investigation_status_is_tenant_isolated():
    created = client.post("/v1/investigations",headers=headers("alarm_management", "CUST-A"),
                          json={"affected_cells": ["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]

    hidden = client.get(f"/v1/investigations/{investigation_id}/status",
                        headers=headers("alarm_management", "CUST-B"))

    assert hidden.status_code == 404


def test_investigation_exposes_state_machine():
    r=client.post("/v1/investigations",headers=headers(),
                  json={"affected_cells":["CELL-PUN-101"]})
    assert r.status_code==200
    assert r.json()["state"] == "RECEIVED"
    assert r.json()["investigation_id"].startswith("INV-")
    state = client.get(f"/v1/investigations/{r.json()['investigation_id']}/status",headers=headers()).json()
    assert state["state"] == "PARTIAL_RESULT"
    assert [entry["state"] for entry in state["history"]] == ["RECEIVED", "IN_PROGRESS", "PARTIAL_RESULT"]


def test_investigation_status_and_late_data_update():
    create = client.post("/v1/investigations",headers=headers(),
                        json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = create.json()["investigation_id"]
    status = client.get(f"/v1/investigations/{investigation_id}/status",headers=headers())
    assert status.status_code == 200
    assert status.json()["state"] == "PARTIAL_RESULT"

    update = client.post(f"/v1/investigations/{investigation_id}/performance-complete",headers=headers(),
                         json={"cell_id":"CELL-PUN-101"})
    assert update.status_code == 200
    assert update.json()["state"] == "COMPLETED"
    assert len(update.json()["history"]) >= 2


def test_investigation_initial_response_is_fast_and_acknowledged():
    started = time.monotonic()
    response = client.post("/v1/investigations",headers=headers(),
                           json={"affected_cells":["CELL-PUN-101"],"incident_time":"2026-11-10T10:05:00Z"})
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 30
    assert response.json()["status"] == "RECEIVED"
    assert response.json()["incident_time"] == "2026-11-10T10:05:00Z"


def test_late_kpi_event_recalculates_investigation():
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]
    event = {
        "event_id": "evt-pun101-late-001",
        "cell_id": "CELL-PUN-101",
        "metric": "availability_pct",
        "window": "10:00-10:15Z",
        "value": 98.75,
        "observed_at": "2026-11-10T10:30:00Z",
    }

    processed = client.post(f"/v1/investigations/{investigation_id}/performance-events",
                            headers=headers(),json=event)
    status = client.get(f"/v1/investigations/{investigation_id}/status",headers=headers()).json()

    assert processed.status_code == 200
    assert processed.json()["calculation_version"] == "availability-v1.3"
    assert processed.json()["state"] == "COMPLETED"
    assert status["findings"][0]["incident_window_availability_pct"] == 98.75
    assert status["findings"][0]["degradation_detected"] is False
    recalculated = database.get_kpi_measurement("CUST-A", "CELL-PUN-101", "availability_pct", "10:00-10:15Z")
    assert recalculated["status"] == "FINAL"
    assert recalculated["value"] == 98.75


def test_missing_kpi_transitions_to_waiting_for_performance_data():
    database.delete_kpi_measurement("CUST-A", "CELL-PUN-101", "availability_pct", "10:00-10:15Z")
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    status = client.get(f"/v1/investigations/{created.json()['investigation_id']}/status",headers=headers()).json()

    assert status["status"] == "WAITING_FOR_PERFORMANCE_DATA"


def test_recalculated_degradation_requires_human_review():
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    event = {"event_id":"evt-degraded-kpi-001","cell_id":"CELL-PUN-101","window":"10:00-10:15Z",
             "value":90.0,"observed_at":"2026-11-10T10:30:00Z"}
    response = client.post(f"/v1/investigations/{created.json()['investigation_id']}/performance-events",
                           headers=headers(),json=event)

    assert response.status_code == 200
    assert response.json()["status"] == "HUMAN_REVIEW_REQUIRED"


def test_background_analysis_failure_sets_failed_state(monkeypatch):
    def fail_analysis(*args):
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(InvestigationService, "process_initial_investigation", staticmethod(fail_analysis))
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    status = client.get(f"/v1/investigations/{created.json()['investigation_id']}/status",headers=headers()).json()

    assert status["status"] == "FAILED"
    assert status["history"][-1]["event"] == "analysis_failed"


def test_duplicate_performance_event_is_idempotent():
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]
    event = {
        "event_id": "evt-pun101-duplicate-001",
        "cell_id": "CELL-PUN-101",
        "metric": "availability_pct",
        "window": "10:00-10:15Z",
        "value": 98.75,
        "observed_at": "2026-11-10T10:30:00Z",
    }
    path = f"/v1/investigations/{investigation_id}/performance-events"
    first = client.post(path,headers=headers(),json=event)
    history_size = len(first.json()["history"])
    duplicate = client.post(path,headers=headers(),json=event)

    assert first.status_code == duplicate.status_code == 200
    assert first.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert len(duplicate.json()["history"]) == history_size
    conflict = client.post(path,headers=headers(),json={**event,"value":97.0})
    assert conflict.status_code == 409
    assert database.get_kpi_measurement("CUST-A", "CELL-PUN-101", "availability_pct", "10:00-10:15Z")["value"] == 98.75


def test_performance_event_isolated_across_tenants():
    created = client.post("/v1/investigations",headers=headers(),json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]
    response = client.post(
        f"/v1/investigations/{investigation_id}/performance-events",
        headers=headers(customer="CUST-B"),
        json={"event_id":"evt-cross-tenant-001","cell_id":"CELL-PUN-101","window":"10:00-10:15Z",
              "value":98.75,"observed_at":"2026-11-10T10:30:00Z"},
    )
    status = client.get(f"/v1/investigations/{investigation_id}/status",headers=headers()).json()

    assert response.status_code == 404
    assert status["state"] == "PARTIAL_RESULT"
    assert database.get_kpi_measurement("CUST-A", "CELL-PUN-101", "availability_pct", "10:00-10:15Z")["value"] == 92.1
    assert database.get_performance_event("evt-cross-tenant-001", "CUST-B") is None


def test_investigation_kpis_events_and_audit_survive_database_restart():
    created = client.post("/v1/investigations",headers=headers(),
                          json={"affected_cells":["CELL-PUN-101"],"incident_time":"2026-11-10T10:05:00Z"})
    investigation_id = created.json()["investigation_id"]
    event = {"event_id":"evt-persistent-001","cell_id":"CELL-PUN-101","metric":"availability_pct",
             "window":"10:00-10:15Z","value":98.75,"observed_at":"2026-11-10T10:30:00Z"}
    processed = client.post(f"/v1/investigations/{investigation_id}/performance-events",
                            headers=headers(),json=event)
    assert processed.status_code == 200

    script = f"""import json
from app import database
from app.services import ENTITIES, KPI_ROWS
database.initialize(KPI_ROWS, ENTITIES)
print(json.dumps({{
    'investigation': database.get_investigation({investigation_id!r}, 'CUST-A'),
    'transitions': database.get_transitions({investigation_id!r}, 'CUST-A'),
    'audit_actions': [row['action'] for row in database.get_audit_records('CUST-A')],
    'kpi': database.get_kpi_measurement('CUST-A', 'CELL-PUN-101', 'availability_pct', '10:00-10:15Z'),
    'event': database.get_performance_event('evt-persistent-001', 'CUST-A'),
}}))"""
    child_env = os.environ.copy()
    child_env["NETWORK_INTELLIGENCE_DB"] = str(database.DB_PATH)
    restarted = subprocess.run(
        [sys.executable, "-c", script],
        cwd=database.PROJECT_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=True,
    )
    restart_data = json.loads(restarted.stdout)

    restored = client.get(f"/v1/investigations/{investigation_id}/status",headers=headers()).json()
    duplicate = client.post(f"/v1/investigations/{investigation_id}/performance-events",
                            headers=headers(),json=event)
    transitions = restart_data["transitions"]
    audit_actions = [record["action"] for record in database.get_audit_records("CUST-A")]
    persisted_kpi = restart_data["kpi"]

    assert restored["status"] == "COMPLETED"
    assert restart_data["investigation"]["status"] == "COMPLETED"
    assert [entry["state"] for entry in restored["history"]] == [
        "RECEIVED", "IN_PROGRESS", "PARTIAL_RESULT", "IN_PROGRESS", "COMPLETED"
    ]
    assert len(transitions) == 5
    assert duplicate.json()["duplicate"] is True
    assert persisted_kpi["value"] == 98.75
    assert persisted_kpi["status"] == "FINAL"
    assert "investigation_created" in audit_actions
    assert "performance_event_processed" in audit_actions
    assert "performance_event_duplicate_ignored" in audit_actions


def test_database_queries_are_customer_scoped():
    created = client.post("/v1/investigations",headers=headers(customer="CUST-A"),
                          json={"affected_cells":["CELL-PUN-101"]})
    investigation_id = created.json()["investigation_id"]

    assert database.get_investigation(investigation_id, "CUST-B") is None
    assert database.get_kpi_measurements("CUST-B", "CELL-PUN-101") == []
    assert database.get_audit_records("CUST-B") == []


def create_change_proposal(customer_id="CUST-A"):
    target_id = "NODE-NOK-02" if customer_id == "CUST-B" else "NODE-ERIC-01"
    return client.post(
        "/v1/change-proposals",
        headers=headers("change_planning", customer_id),
        json={"target_id": target_id, "action": "restart", "rationale": "Restart only after human review"},
    )


def approval_headers(user_id="approver-cust-a"):
    return {"X-Demo-User-ID": user_id}


def test_authorized_approver_approves_without_execution():
    proposal = create_change_proposal()
    assert proposal.status_code == 200
    assert proposal.json()["status"] == "PENDING_HUMAN_APPROVAL"
    assert proposal.json()["executed"] is False

    approved = client.post(
        f"/v1/change-proposals/{proposal.json()['proposal_id']}/approve",
        headers=approval_headers(),json={"note":"Reviewed synthetic impact"},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED_BY_HUMAN_REVIEWER"
    assert approved.json()["approval_decision"] == "APPROVED"
    assert approved.json()["approved_by"] == "approver-cust-a"
    assert approved.json()["decision_history"][0]["timestamp"]
    assert approved.json()["executed"] is False


def test_known_unauthorized_user_cannot_approve():
    proposal = create_change_proposal()
    unauthorized = client.post(
        f"/v1/change-proposals/{proposal.json()['proposal_id']}/approve",
        headers={"X-Demo-User-ID":"planner-cust-a"},json={},
    )
    assert unauthorized.status_code == 403


def test_unknown_or_missing_approval_user_is_unauthorized():
    proposal = create_change_proposal()
    path = f"/v1/change-proposals/{proposal.json()['proposal_id']}/approve"
    assert client.post(path,headers={"X-Demo-User-ID":"unknown-user"},json={}).status_code == 401
    assert client.post(path,json={}).status_code == 401


def test_cross_tenant_approver_cannot_decide_proposal():
    proposal = create_change_proposal("CUST-B")
    cross_tenant = client.post(
        f"/v1/change-proposals/{proposal.json()['proposal_id']}/approve",
        headers=approval_headers("approver-cust-a"),json={},
    )
    assert cross_tenant.status_code == 404
    assert client.get("/v1/change-proposals",headers=headers("change_planning","CUST-B")).json()[0]["status"] == "PENDING_HUMAN_APPROVAL"


def test_duplicate_decision_is_rejected_and_never_executes():
    proposal = create_change_proposal()
    path = f"/v1/change-proposals/{proposal.json()['proposal_id']}/approve"
    approved = client.post(path,headers=approval_headers(),json={})
    duplicate = client.post(path,headers=approval_headers(),json={})
    rejected_after_approval = client.post(
        f"/v1/change-proposals/{proposal.json()['proposal_id']}/reject",
        headers=approval_headers(),json={},
    )

    assert approved.status_code == 200
    assert duplicate.status_code == 409
    assert rejected_after_approval.status_code == 409
    assert approved.json()["executed"] is False


def test_approver_can_reject_with_auditable_decision():
    proposal = create_change_proposal()
    rejected = client.post(
        f"/v1/change-proposals/{proposal.json()['proposal_id']}/reject",
        headers=approval_headers(),json={"note":"Impact not acceptable"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED_BY_HUMAN_REVIEWER"
    assert rejected.json()["approval_decision"] == "REJECTED"
    assert rejected.json()["decided_by"] == "approver-cust-a"
    assert rejected.json()["decision_history"][0]["note"] == "Impact not acceptable"
    assert rejected.json()["executed"] is False


def test_approval_decision_survives_application_restart(tmp_path, monkeypatch):
    proposal = create_change_proposal()
    proposal_id = proposal.json()["proposal_id"]
    approved = client.post(
        f"/v1/change-proposals/{proposal_id}/approve",
        headers=approval_headers(),json={"note":"Restart persistence check"},
    )
    assert approved.status_code == 200

    script = f"""import json
from app import database
from app.services import ENTITIES, KPI_ROWS
database.initialize(KPI_ROWS, ENTITIES)
print(json.dumps(database.get_change_proposal({proposal_id!r}, 'CUST-A')))
"""
    child_env = os.environ.copy()
    child_env["NETWORK_INTELLIGENCE_DB"] = str(database.DB_PATH)
    restarted = subprocess.run(
        [sys.executable, "-c", script], cwd=database.PROJECT_ROOT, env=child_env,
        capture_output=True, text=True, check=True,
    )
    persisted = json.loads(restarted.stdout)

    assert persisted["status"] == "APPROVED_BY_HUMAN_REVIEWER"
    assert persisted["approved_by"] == "approver-cust-a"
    assert persisted["approval_timestamp"]
    assert persisted["decision_history"][0]["decision"] == "APPROVED"
    assert persisted["executed"] is False


def test_all_proposal_states_remain_non_executing():
    pending = create_change_proposal()
    approved = client.post(
        f"/v1/change-proposals/{pending.json()['proposal_id']}/approve",
        headers=approval_headers(),json={},
    )
    rejected_proposal = create_change_proposal()
    rejected = client.post(
        f"/v1/change-proposals/{rejected_proposal.json()['proposal_id']}/reject",
        headers=approval_headers(),json={},
    )
    proposals = client.get("/v1/change-proposals",headers=headers("change_planning")).json()

    assert approved.status_code == rejected.status_code == 200
    assert all(proposal["executed"] is False for proposal in proposals)
