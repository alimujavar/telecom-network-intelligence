# API Reference

FastAPI publishes the live OpenAPI/Swagger UI at `http://127.0.0.1:8000/docs`. All data is synthetic and local. The APIs use demo identity headers; they are not production authentication.

## Identity

General routes accept `X-Demo-Role` and `X-Customer-ID`. Known roles are `alarm_management`, `performance_analysis`, `change_planning`, `change_approver`, and `platform_admin`. Approval routes instead require `X-Demo-User-ID`; they resolve role and tenant from the backend registry and ignore role/customer headers for authorization.

Registered local approvers:

| User ID | Role | Customer |
| --- | --- | --- |
| `approver-cust-a` | `change_approver` | `CUST-A` |
| `approver-cust-b` | `change_approver` | `CUST-B` |

## Endpoints

| Method | Path | Authorization | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | None | Health/status check |
| `GET` | `/v1/topology/{entity_id}?depth=2` | `topology:read` | Tenant-scoped two-hop synthetic topology |
| `GET` | `/v1/kpis/{entity_id}` | `kpi:read` | Tenant-scoped KPI series and completeness |
| `POST` | `/v1/investigations` | `topology:read` + `kpi:read` | Persist and acknowledge investigation, then analyze asynchronously |
| `GET` | `/v1/investigations/{investigation_id}/status` | `kpi:read` | Tenant-scoped current state, findings, and history |
| `POST` | `/v1/investigations/{investigation_id}/performance-events` | `kpi:read` | Persist and process an idempotent late KPI event |
| `POST` | `/v1/investigations/{investigation_id}/performance-complete` | `kpi:read` | Synthetic late-data compatibility endpoint |
| `POST` | `/v1/change-proposals` | `change:propose` | Create a proposal in `PENDING_HUMAN_APPROVAL` |
| `GET` | `/v1/change-proposals` | `change:read` or `change:approve` | List proposals for the authenticated customer |
| `POST` | `/v1/change-proposals/{proposal_id}/approve` | Registered `change_approver` user | Persist one approval decision |
| `POST` | `/v1/change-proposals/{proposal_id}/reject` | Registered `change_approver` user | Persist one rejection decision |

## Proposal decisions

Create a proposal with `X-Demo-Role: change_planning` and `X-Customer-ID: CUST-A`:

```json
{
  "target_id": "NODE-ERIC-01",
  "action": "restart",
  "rationale": "Restart only after human review"
}
```

The initial response has `status: PENDING_HUMAN_APPROVAL` and `executed: false`. Approve or reject with an approver user ID and an optional note:

```json
{"note": "Reviewed synthetic impact"}
```

Decision statuses are `APPROVED_BY_HUMAN_REVIEWER` and `REJECTED_BY_HUMAN_REVIEWER`. Each response includes the decision, approver identity, timestamp, decision history, and `executed: false`. Repeating a final decision returns `409`.

## Error behavior

- `401`: unknown role or missing/unknown approval user ID.
- `403`: known user/role lacks the required permission.
- `404`: entity or proposal does not exist in the caller's customer scope.
- `409`: proposal already has a final decision or event ID conflicts with a prior payload.
- `422`: request validation failed.

No endpoint executes a real or synthetic network action. See [the API contract](api-contract.json) for the machine-readable contract.
