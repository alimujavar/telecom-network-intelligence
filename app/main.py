from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import (
    AuthorizationService,
    ChangeProposalService,
    InventoryService,
    InvestigationService,
    KPIService,
    ROLE_PERMISSIONS,
)

app = FastAPI(title="Telecom Network Intelligence Prototype", version="0.1.0")


def identity(x_demo_role: str = Header("alarm_management"), x_customer_id: str = Header("CUST-A")):
    try:
        return AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc


def require(principal, permission):
    try:
        AuthorizationService.require(principal, permission)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def visible_entity(entity_id, principal):
    try:
        return InventoryService.visible_entity(entity_id, principal)
    except LookupError as exc:
        raise HTTPException(404, "Entity not found") from exc


@app.get("/health")
def health():
    return {"status": "ok", "prototype": "demo-data", "utc": datetime.now(timezone.utc).isoformat()}


@app.get("/topology/{entity_id}")
def topology(entity_id: str, depth: int = Query(2, ge=1, le=2), principal=Header(None)):
    raise HTTPException(501, "Use /v1/topology/{entity_id}; legacy route disabled")


@app.get("/v1/topology/{entity_id}")
def get_topology(entity_id: str, depth: int = Query(2, ge=1, le=2),
                 x_demo_role: str = Header("alarm_management"), x_customer_id: str = Header("CUST-A")):
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "topology:read")
    visible_entity(entity_id, p)
    return InventoryService.topology_neighborhood(entity_id, depth, p["customer_id"])


@app.get("/v1/kpis/{entity_id}")
def get_kpis(entity_id: str, x_demo_role: str = Header("alarm_management"),
             x_customer_id: str = Header("CUST-A")):
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "kpi:read")
    visible_entity(entity_id, p)
    rows = KPIService.get_series(entity_id, p)
    return {
        "entity_id": entity_id,
        "customer_id": p["customer_id"],
        "series": rows,
        "completeness": KPIService.completeness(rows),
        "late_data_allowance_minutes": 120,
        "formula_version": "availability-v1.2",
        "provenance": {"source": "demo_kpi_store", "calculation_run": "kpi-run-20261110-1015"},
    }


class InvestigationRequest(BaseModel):
    affected_cells: list[str] = Field(min_length=1, max_length=20)
    incident_time: str = "2026-11-10T10:05:00Z"


class InvestigationResponse(BaseModel):
    investigation_id: str
    customer_id: str
    affected_cells: list[str]
    status: str
    state: str
    created_at: str
    updated_at: str
    evidence_completeness: str
    completeness: str
    topology_snapshot_id: str | None
    recommendations: list[str]
    incident_time: str
    findings: list[dict[str, Any]]
    initial_assessment: str
    recommended_next_step: str
    action_executed: bool
    human_approval_required: bool
    limitations: list[str]
    history: list[dict[str, Any]]


class InvestigationStatusResponse(BaseModel):
    investigation_id: str
    affected_cells: list[str]
    status: str
    state: str
    customer_id: str
    created_at: str
    evidence_completeness: str
    completeness: str
    topology_snapshot_id: str | None
    recommendations: list[str]
    updated_at: str
    history: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    calculation_version: str


@app.post("/v1/investigations")
def investigate(req: InvestigationRequest, background_tasks: BackgroundTasks,
                x_demo_role: str = Header("alarm_management"),
                x_customer_id: str = Header("CUST-A")) -> InvestigationResponse:
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "topology:read")
    require(p, "kpi:read")
    try:
        result = InvestigationService.create_investigation(
            req.affected_cells, p["customer_id"], req.incident_time, p["role"]
        )
    except LookupError as exc:
        raise HTTPException(404, "Entity not found") from exc
    background_tasks.add_task(
        InvestigationService.process_initial_safely,
        result["investigation_id"],
        p["customer_id"],
    )
    return InvestigationResponse(**result)


@app.get("/v1/investigations/{investigation_id}/status")
def get_investigation_status(investigation_id: str, x_demo_role: str = Header("alarm_management"),
                            x_customer_id: str = Header("CUST-A")) -> InvestigationStatusResponse:
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "kpi:read")
    try:
        return InvestigationService.get_status(investigation_id, p["customer_id"])
    except LookupError as exc:
        raise HTTPException(404, "Investigation not found") from exc


class PerformanceCompletionRequest(BaseModel):
    cell_id: str | None = None


class PerformanceEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    cell_id: str
    metric: Literal["availability_pct"] = "availability_pct"
    window: str
    value: float = Field(ge=0, le=100)
    observed_at: str


class PerformanceEventResponse(BaseModel):
    investigation_id: str
    event_id: str
    status: str
    state: str
    customer_id: str
    updated_at: str
    completeness: str
    evidence_completeness: str
    findings: list[dict[str, Any]]
    duplicate: bool
    history: list[dict[str, Any]]
    calculation_version: str


@app.post("/v1/investigations/{investigation_id}/performance-events")
def process_performance_event(investigation_id: str, req: PerformanceEventRequest,
                              x_demo_role: str = Header("alarm_management"),
                              x_customer_id: str = Header("CUST-A")) -> PerformanceEventResponse:
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "kpi:read")
    try:
        result = InvestigationService.process_performance_event(
            investigation_id,
            p["customer_id"],
            req.model_dump(),
            p["role"],
        )
        return PerformanceEventResponse(**result)
    except LookupError as exc:
        raise HTTPException(404, "Investigation or affected cell not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/investigations/{investigation_id}/performance-complete")
def complete_performance(investigation_id: str, req: PerformanceCompletionRequest,
                        x_demo_role: str = Header("alarm_management"), x_customer_id: str = Header("CUST-A")):
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "kpi:read")
    try:
        return InvestigationService.simulate_late_performance(
            investigation_id, p["customer_id"], req.cell_id, p["role"]
        )
    except LookupError as exc:
        raise HTTPException(404, "Investigation not found") from exc


class ActionProposal(BaseModel):
    target_id: str
    action: str
    rationale: str = Field(min_length=10, max_length=1000)


class ProposalDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


def _decide_change_proposal(proposal_id: str, decision: str, req: ProposalDecisionRequest,
                            x_demo_user_id: str | None) -> dict[str, Any]:
    try:
        user = AuthorizationService.demo_user(x_demo_user_id or "")
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo user") from exc
    require(user, "change:approve")
    try:
        return ChangeProposalService.decide(
            proposal_id, user["customer_id"], decision, user, req.note
        )
    except LookupError as exc:
        raise HTTPException(404, "Change proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/change-proposals")
def propose_change(req: ActionProposal, x_demo_role: str = Header("change_planning"),
                   x_customer_id: str = Header("CUST-A")):
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    require(p, "change:propose")
    try:
        return ChangeProposalService.create(req.target_id, req.action, req.rationale, p["customer_id"], p["role"])
    except LookupError as exc:
        raise HTTPException(404, "Entity not found") from exc


@app.get("/v1/change-proposals")
def list_change_proposals(x_demo_role: str = Header("change_planning"),
                          x_customer_id: str = Header("CUST-A")):
    try:
        p = AuthorizationService.principal(x_demo_role, x_customer_id)
    except ValueError as exc:
        raise HTTPException(401, "Unknown demo role") from exc
    if not ({"change:read", "change:approve"} & ROLE_PERMISSIONS[p["role"]]):
        raise HTTPException(403, f"Role '{p['role']}' lacks change:read")
    return ChangeProposalService.list_for_customer(p["customer_id"])


@app.post("/v1/change-proposals/{proposal_id}/approve")
def approve_change_proposal(proposal_id: str, req: ProposalDecisionRequest = ProposalDecisionRequest(),
                            x_demo_user_id: str | None = Header(None)):
    return _decide_change_proposal(proposal_id, "APPROVED", req, x_demo_user_id)


@app.post("/v1/change-proposals/{proposal_id}/reject")
def reject_change_proposal(proposal_id: str, req: ProposalDecisionRequest = ProposalDecisionRequest(),
                           x_demo_user_id: str | None = Header(None)):
    return _decide_change_proposal(proposal_id, "REJECTED", req, x_demo_user_id)

