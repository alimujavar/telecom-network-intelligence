from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Iterable, List, Tuple
from uuid import uuid4

from app import database

ROLE_PERMISSIONS = {
    "alarm_management": {"topology:read", "kpi:read", "incident:propose"},
    "performance_analysis": {"topology:read", "kpi:read", "analysis:export"},
    "change_planning": {"topology:read", "kpi:read", "change:read", "change:simulate", "change:propose"},
    "change_approver": {"topology:read", "kpi:read", "change:read", "change:approve"},
    "platform_admin": {"topology:read", "kpi:read", "incident:propose", "change:read", "change:simulate", "change:propose", "admin:write"},
}

DEMO_USERS = {
    "planner-cust-a": {"role": "change_planning", "customer_id": "CUST-A"},
    "planner-cust-b": {"role": "change_planning", "customer_id": "CUST-B"},
    "approver-cust-a": {"role": "change_approver", "customer_id": "CUST-A"},
    "approver-cust-b": {"role": "change_approver", "customer_id": "CUST-B"},
}

ENTITIES = {
    "CELL-PUN-101": {"id": "CELL-PUN-101", "type": "cell", "name": "Pune-Central-Cell-101", "customer_id": "CUST-A", "site_id": "SITE-PUN-01", "node_id": "NODE-ERIC-01", "service_id": "SVC-VOICE-01"},
    "CELL-PUN-102": {"id": "CELL-PUN-102", "type": "cell", "name": "Pune-Central-Cell-102", "customer_id": "CUST-A", "site_id": "SITE-PUN-01", "node_id": "NODE-ERIC-01", "service_id": "SVC-DATA-01"},
    "SITE-PUN-01": {"id": "SITE-PUN-01", "type": "site", "name": "Pune Central Site", "customer_id": "CUST-A"},
    "NODE-ERIC-01": {"id": "NODE-ERIC-01", "type": "node", "name": "Ericsson RAN Node 01", "customer_id": "CUST-A", "transport_id": "TX-PUN-01"},
    "TX-PUN-01": {"id": "TX-PUN-01", "type": "transport", "name": "Pune Metro Ring 01", "customer_id": "CUST-A"},
    "SVC-VOICE-01": {"id": "SVC-VOICE-01", "type": "service", "name": "Voice Service", "customer_id": "CUST-A"},
    "SVC-DATA-01": {"id": "SVC-DATA-01", "type": "service", "name": "Data Service", "customer_id": "CUST-A"},
    "CELL-MUM-201": {"id": "CELL-MUM-201", "type": "cell", "name": "Mumbai-Cell-201", "customer_id": "CUST-B", "site_id": "SITE-MUM-02", "node_id": "NODE-NOK-02", "service_id": "SVC-MUM-01"},
    "SITE-MUM-02": {"id": "SITE-MUM-02", "type": "site", "name": "Mumbai Site 02", "customer_id": "CUST-B"},
    "NODE-NOK-02": {"id": "NODE-NOK-02", "type": "node", "name": "Nokia Node 02", "customer_id": "CUST-B"},
    "SVC-MUM-01": {"id": "SVC-MUM-01", "type": "service", "name": "Mumbai Data Service", "customer_id": "CUST-B"},
}

RELATIONSHIPS = [
    ("CELL-PUN-101", "SITE-PUN-01", "located_at"),
    ("CELL-PUN-101", "NODE-ERIC-01", "served_by"),
    ("CELL-PUN-101", "SVC-VOICE-01", "supports"),
    ("CELL-PUN-102", "SITE-PUN-01", "located_at"),
    ("CELL-PUN-102", "NODE-ERIC-01", "served_by"),
    ("CELL-PUN-102", "SVC-DATA-01", "supports"),
    ("NODE-ERIC-01", "TX-PUN-01", "backhauled_by"),
    ("CELL-MUM-201", "SITE-MUM-02", "located_at"),
    ("CELL-MUM-201", "NODE-NOK-02", "served_by"),
    ("CELL-MUM-201", "SVC-MUM-01", "supports"),
]

KPI_ROWS = {
    "CELL-PUN-101": [
        {"metric": "availability_pct", "window": "09:45-10:00Z", "value": 99.95, "status": "VALID", "observed_at": "2026-11-10T10:00:00Z"},
        {"metric": "availability_pct", "window": "10:00-10:15Z", "value": 92.10, "status": "PROVISIONAL", "observed_at": "2026-11-10T10:15:00Z"},
        {"metric": "dl_prb_util_pct", "window": "09:45-10:00Z", "value": 72.0, "status": "VALID", "observed_at": "2026-11-10T10:00:00Z"},
        {"metric": "dl_prb_util_pct", "window": "10:00-10:15Z", "value": 94.0, "status": "PROVISIONAL", "observed_at": "2026-11-10T10:15:00Z"},
    ],
    "CELL-PUN-102": [
        {"metric": "availability_pct", "window": "09:45-10:00Z", "value": 99.91, "status": "VALID", "observed_at": "2026-11-10T10:00:00Z"},
        {"metric": "availability_pct", "window": "10:00-10:15Z", "value": 91.70, "status": "PROVISIONAL", "observed_at": "2026-11-10T10:15:00Z"},
    ],
}

INVESTIGATION_STATES = {
    "RECEIVED",
    "IN_PROGRESS",
    "WAITING_FOR_PERFORMANCE_DATA",
    "PARTIAL_RESULT",
    "COMPLETED",
    "FAILED",
    "HUMAN_REVIEW_REQUIRED",
}

PERFORMANCE_EVENT_LOCK = Lock()
STATE_TRANSITIONS = {
    "RECEIVED": {"IN_PROGRESS", "FAILED"},
    "IN_PROGRESS": {"WAITING_FOR_PERFORMANCE_DATA", "PARTIAL_RESULT", "COMPLETED", "FAILED", "HUMAN_REVIEW_REQUIRED"},
    "WAITING_FOR_PERFORMANCE_DATA": {"IN_PROGRESS", "PARTIAL_RESULT", "COMPLETED", "FAILED"},
    "PARTIAL_RESULT": {"IN_PROGRESS", "COMPLETED", "FAILED", "HUMAN_REVIEW_REQUIRED"},
    "COMPLETED": {"IN_PROGRESS"},
    "FAILED": set(),
    "HUMAN_REVIEW_REQUIRED": {"IN_PROGRESS", "COMPLETED"},
}


class AuthorizationService:
    @staticmethod
    def principal(role: str, customer_id: str) -> Dict[str, str]:
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"Unknown demo role: {role}")
        return {"role": role, "customer_id": customer_id}

    @staticmethod
    def require(principal: Dict[str, str], permission: str) -> None:
        if permission not in ROLE_PERMISSIONS[principal["role"]]:
            raise PermissionError(f"Role '{principal['role']}' lacks {permission}")

    @staticmethod
    def demo_user(user_id: str) -> Dict[str, str]:
        user = DEMO_USERS.get(user_id)
        if not user:
            raise ValueError("Unknown demo user")
        return {**user, "user_id": user_id}


class InventoryService:
    @staticmethod
    def visible_entity(entity_id: str, principal: Dict[str, str]) -> Dict[str, Any]:
        entity = ENTITIES.get(entity_id)
        if not entity or entity["customer_id"] != principal["customer_id"]:
            raise LookupError("Entity not found")
        return entity

    @staticmethod
    def topology_neighborhood(entity_id: str, depth: int, customer_id: str) -> Dict[str, Any]:
        frontier, seen, edges = {entity_id}, {entity_id}, []
        for _ in range(depth):
            next_frontier = set()
            for a, b, rel in RELATIONSHIPS:
                if a in frontier and ENTITIES[b]["customer_id"] == customer_id:
                    edges.append({"from": a, "to": b, "type": rel})
                    next_frontier.add(b)
                elif b in frontier and ENTITIES[a]["customer_id"] == customer_id:
                    edges.append({"from": b, "to": a, "type": rel})
                    next_frontier.add(a)
            next_frontier -= seen
            seen |= next_frontier
            frontier = next_frontier
        nodes = [ENTITIES[i] for i in sorted(seen)]
        return {
            "request_id": "demo-topo-001",
            "customer_id": customer_id,
            "root": entity_id,
            "depth": depth,
            "nodes": nodes,
            "relationships": edges,
            "as_of": "2026-11-10T10:05:00Z",
            "completeness": "COMPLETE",
            "provenance": {"source": "normalized_inventory_snapshot", "snapshot_id": "inv-20261110-1000"},
            "errors": [],
        }


class KPIService:
    @staticmethod
    def get_series(entity_id: str, principal: Dict[str, str]) -> List[Dict[str, Any]]:
        InventoryService.visible_entity(entity_id, principal)
        return database.get_kpi_measurements(principal["customer_id"], entity_id)

    @staticmethod
    def completeness(rows: Iterable[Dict[str, Any]]) -> str:
        rows = list(rows)
        if not rows:
            return "UNAVAILABLE"
        if any(r.get("status") != "VALID" for r in rows):
            return "PARTIAL"
        return "COMPLETE"


class InvestigationService:
    @staticmethod
    def make_investigation_id() -> str:
        return f"INV-{uuid4().hex.upper()}"

    @staticmethod
    def get_investigation(investigation_id: str, customer_id: str) -> Dict[str, Any]:
        investigation = database.get_investigation(investigation_id, customer_id)
        if not investigation:
            raise LookupError("Investigation not found")
        return investigation

    @staticmethod
    def _transition(investigation: Dict[str, Any], status: str, event: str, actor_role: str = "system") -> None:
        current = investigation["status"]
        if status != current and status not in STATE_TRANSITIONS[current]:
            raise ValueError(f"Invalid investigation transition: {current} -> {status}")
        if status != current:
            investigation["status"] = status
            investigation["state"] = status
            investigation["updated_at"] = datetime.now(timezone.utc).isoformat()
            investigation["history"].append({
                "event": event,
                "state": status,
                "timestamp": investigation["updated_at"],
                "calculation_version": investigation["calculation_version"],
            })
            database.save_transition(investigation, current, event, actor_role)

    @staticmethod
    def create_investigation(affected_cells: List[str], customer_id: str, incident_time: str,
                             actor_role: str = "alarm_management") -> Dict[str, Any]:
        principal = {"role": "alarm_management", "customer_id": customer_id}
        for cell in affected_cells:
            InventoryService.visible_entity(cell, principal)
        topology = InventoryService.topology_neighborhood(affected_cells[0], 2, customer_id)
        investigation_id = InvestigationService.make_investigation_id()
        while database.get_investigation(investigation_id, customer_id):
            investigation_id = InvestigationService.make_investigation_id()
        created_at = datetime.now(timezone.utc).isoformat()
        result = {
            "investigation_id": investigation_id,
            "affected_cells": list(affected_cells),
            "status": "RECEIVED",
            "state": "RECEIVED",
            "incident_time": incident_time,
            "customer_id": customer_id,
            "findings": [],
            "initial_assessment": "Investigation accepted; evidence collection is starting.",
            "recommended_next_step": "Await investigation analysis.",
            "recommendations": ["Await investigation analysis."],
            "action_executed": False,
            "human_approval_required": True,
            "completeness": "UNAVAILABLE",
            "evidence_completeness": "UNAVAILABLE",
            "topology_snapshot_id": topology["provenance"]["snapshot_id"],
            "limitations": ["Synthetic demo dataset", "No live vendor feed", "No production action connector"],
            "created_at": created_at,
            "updated_at": created_at,
            "calculation_version": "availability-v1.2",
            "history": [{
                "event": "alarm_received",
                "state": "RECEIVED",
                "timestamp": created_at,
                "calculation_version": "availability-v1.2",
            }],
        }
        database.create_investigation(result, actor_role)
        return result

    @staticmethod
    def process_initial_investigation(investigation_id: str, customer_id: str) -> Dict[str, Any]:
        investigation = InvestigationService.get_investigation(investigation_id, customer_id)
        InvestigationService._transition(investigation, "IN_PROGRESS", "analysis_started")
        findings: List[Dict[str, Any]] = []
        principal = {"role": "alarm_management", "customer_id": customer_id}
        for cell in investigation["affected_cells"]:
            topo = InventoryService.topology_neighborhood(cell, 2, customer_id)
            kpis = database.get_kpi_measurements(customer_id, cell)
            vals = [r for r in kpis if r["metric"] == "availability_pct"]
            baseline = next((r["value"] for r in vals if r["window"] == "09:45-10:00Z"), None)
            current_row = next((r for r in vals if r["window"] == "10:00-10:15Z"), None)
            current = current_row["value"] if current_row else None
            findings.append({
                "cell_id": cell,
                "baseline_availability_pct": baseline,
                "incident_window_availability_pct": current,
                "degradation_detected": baseline is not None and current is not None and (baseline - current) > 2,
                "shared_transport": [n["id"] for n in topo["nodes"] if n["type"] == "transport"],
                "evidence_status": (
                    "FINAL_KPI" if current_row and current_row.get("status") == "FINAL"
                    else "PROVISIONAL_KPI" if current_row else "MISSING_KPI"
                ),
                "topology_snapshot": topo["provenance"]["snapshot_id"],
            })

        investigation["findings"] = findings
        investigation["topology_snapshot_id"] = findings[0]["topology_snapshot"] if findings else None
        provisional = any(f["evidence_status"] == "PROVISIONAL_KPI" for f in findings)
        missing = any(f["evidence_status"] == "MISSING_KPI" for f in findings)
        degraded = any(f["degradation_detected"] for f in findings)
        if provisional:
            state = "PARTIAL_RESULT"
            completeness = "PARTIAL"
        elif missing:
            state = "WAITING_FOR_PERFORMANCE_DATA"
            completeness = "UNAVAILABLE"
        else:
            state = "HUMAN_REVIEW_REQUIRED" if degraded else "COMPLETED"
            completeness = "COMPLETE"
        investigation["completeness"] = completeness
        investigation["evidence_completeness"] = completeness
        recommendation = "Review the provisional KPI evidence and await final performance data." if provisional else "Validate delayed performance counters before taking action."
        investigation["initial_assessment"] = "Potential correlated degradation; current KPI windows are provisional."
        investigation["recommended_next_step"] = recommendation
        investigation["recommendations"] = [recommendation]
        InvestigationService._transition(investigation, state, "initial_analysis_complete")
        database.update_investigation(investigation)
        return investigation

    @staticmethod
    def process_initial_safely(investigation_id: str, customer_id: str) -> None:
        try:
            InvestigationService.process_initial_investigation(investigation_id, customer_id)
        except Exception:
            investigation = database.get_investigation(investigation_id, customer_id)
            if investigation and investigation["customer_id"] == customer_id and investigation["status"] != "FAILED":
                investigation["failure_reason"] = "Initial analysis failed."
                InvestigationService._transition(investigation, "FAILED", "analysis_failed")

    @staticmethod
    def get_status(investigation_id: str, customer_id: str) -> Dict[str, Any]:
        investigation = InvestigationService.get_investigation(investigation_id, customer_id)
        return {
            "investigation_id": investigation["investigation_id"],
            "affected_cells": investigation["affected_cells"],
            "status": investigation["status"],
            "state": investigation["state"],
            "customer_id": investigation["customer_id"],
            "created_at": investigation["created_at"],
            "evidence_completeness": investigation["evidence_completeness"],
            "completeness": investigation["completeness"],
            "topology_snapshot_id": investigation["topology_snapshot_id"],
            "recommendations": investigation["recommendations"],
            "updated_at": investigation["updated_at"],
            "history": investigation.get("history", []),
            "findings": investigation["findings"],
            "calculation_version": investigation.get("calculation_version", "availability-v1.2"),
        }

    @staticmethod
    def process_performance_event(investigation_id: str, customer_id: str, event: Dict[str, Any],
                                  actor_role: str = "alarm_management") -> Dict[str, Any]:
        with PERFORMANCE_EVENT_LOCK:
            return InvestigationService._process_performance_event(investigation_id, customer_id, event, actor_role)

    @staticmethod
    def _process_performance_event(investigation_id: str, customer_id: str, event: Dict[str, Any],
                                   actor_role: str) -> Dict[str, Any]:
        investigation = InvestigationService.get_investigation(investigation_id, customer_id)
        event_id = event["event_id"]
        fingerprint = {
            "investigation_id": investigation_id,
            **{key: value for key, value in event.items() if key != "event_id"},
        }
        previous = database.get_performance_event(event_id, customer_id)
        if previous:
            if previous["investigation_id"] != investigation_id:
                raise ValueError("Event ID was already used for a different investigation")
            if previous["fingerprint"] != fingerprint:
                raise ValueError("Event ID was already used with a different payload")
            database.add_audit_record(
                customer_id, actor_role, "performance_event_duplicate_ignored", investigation_id,
                datetime.now(timezone.utc).isoformat(), {"event_id": event_id},
            )
            return {**previous["response"], "duplicate": True}

        cell_id = event["cell_id"]
        affected_cells = investigation["affected_cells"]
        if cell_id not in affected_cells:
            raise LookupError("Cell not found in investigation")
        InventoryService.visible_entity(cell_id, {"role": "alarm_management", "customer_id": customer_id})

        database.upsert_kpi_measurement(customer_id, cell_id, {
            "metric": event["metric"],
            "window": event["window"],
            "value": event["value"],
            "status": "FINAL",
            "observed_at": event["observed_at"],
        })

        InvestigationService._transition(investigation, "IN_PROGRESS", "performance_event_received")
        investigation["calculation_version"] = "availability-v1.3"
        database.update_investigation(investigation)
        investigation = InvestigationService.process_initial_investigation(investigation_id, customer_id)
        result_state = investigation["status"]
        investigation["completeness"] = "COMPLETE" if all(
            finding["evidence_status"] == "FINAL_KPI" for finding in investigation["findings"]
        ) else investigation["completeness"]
        investigation["evidence_completeness"] = investigation["completeness"]
        investigation["recommended_next_step"] = (
            "Human review required for recalculated degradation." if result_state == "HUMAN_REVIEW_REQUIRED"
            else "Late KPI reconciled; no immediate change action is required." if result_state == "COMPLETED"
            else "Await remaining final KPI evidence."
        )
        investigation["recommendations"] = [investigation["recommended_next_step"]]
        response = {
            "investigation_id": investigation["investigation_id"],
            "event_id": event_id,
            "status": investigation["status"],
            "state": investigation["status"],
            "customer_id": investigation["customer_id"],
            "updated_at": investigation["updated_at"],
            "completeness": investigation["completeness"],
            "evidence_completeness": investigation["evidence_completeness"],
            "findings": investigation["findings"],
            "duplicate": False,
            "history": investigation["history"],
            "calculation_version": investigation["calculation_version"],
        }
        event_created_at = datetime.now(timezone.utc).isoformat()
        database.save_performance_event(event_id, customer_id, investigation_id, fingerprint, response, event_created_at)
        database.add_audit_record(
            customer_id, actor_role, "performance_event_processed", investigation_id,
            event_created_at, {"event_id": event_id, "cell_id": cell_id, "status": response["status"]},
        )
        return response

    @staticmethod
    def simulate_late_performance(investigation_id: str, customer_id: str, cell_id: str | None = None,
                                  actor_role: str = "alarm_management") -> Dict[str, Any]:
        investigation = InvestigationService.get_investigation(investigation_id, customer_id)
        target_cells = [cell_id] if cell_id else investigation["affected_cells"]
        result = None
        for target_cell in target_cells:
            result = InvestigationService.process_performance_event(investigation_id, customer_id, {
                "event_id": f"synthetic-late-kpi-{investigation_id}-{target_cell}",
                "cell_id": target_cell,
                "metric": "availability_pct",
                "window": "10:00-10:15Z",
                "value": 98.75,
                "observed_at": "2026-11-10T10:30:00Z",
            }, actor_role)
        return result or {}


class ChangeProposalService:
    @staticmethod
    def create(target_id: str, action: str, rationale: str, customer_id: str,
               proposer_role: str) -> Dict[str, Any]:
        InventoryService.visible_entity(target_id, {"role": proposer_role, "customer_id": customer_id})
        created_at = datetime.now(timezone.utc).isoformat()
        record = {
            "proposal_id": f"CHG-{uuid4().hex[:12].upper()}",
            "customer_id": customer_id,
            "target_id": target_id,
            "action": action,
            "rationale": rationale,
            "status": "PENDING_HUMAN_APPROVAL",
            "proposed_by": proposer_role,
            "created_at": created_at,
            "updated_at": created_at,
            "approval_decision": None,
            "approver_role": None,
            "decided_by": None,
            "approved_by": None,
            "approval_timestamp": None,
            "decision_history": [],
            "executed": False,
        }
        database.create_change_proposal(record, proposer_role)
        return record

    @staticmethod
    def get(proposal_id: str, customer_id: str) -> Dict[str, Any]:
        record = database.get_change_proposal(proposal_id, customer_id)
        if not record:
            raise LookupError("Change proposal not found")
        return record

    @staticmethod
    def list_for_customer(customer_id: str) -> List[Dict[str, Any]]:
        return database.list_change_proposals(customer_id)

    @staticmethod
    def decide(proposal_id: str, customer_id: str, decision: str, user: Dict[str, str],
               note: str | None = None) -> Dict[str, Any]:
        if user["role"] != "change_approver":
            raise PermissionError("Role 'change_approver' is required")
        if user["customer_id"] != customer_id:
            raise LookupError("Change proposal not found")
        decided_at = datetime.now(timezone.utc).isoformat()
        return database.decide_change_proposal(
            proposal_id, customer_id, decision, user["user_id"], user["role"], decided_at, note
        )


    database.initialize(KPI_ROWS, ENTITIES)
