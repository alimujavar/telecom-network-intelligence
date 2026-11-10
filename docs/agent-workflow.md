# Agent workflow and investigation lifecycle

## Lifecycle states

- RECEIVED
- IN_PROGRESS
- WAITING_FOR_PERFORMANCE_DATA
- PARTIAL_RESULT
- COMPLETED
- FAILED
- HUMAN_REVIEW_REQUIRED

## Flow

1. An alarm arrives with customer, role, incident time and affected cell IDs.
2. The API validates role and tenant scope, stores the investigation as `RECEIVED`, and returns without waiting for analysis.
3. A local FastAPI background task moves the record to `IN_PROGRESS` and collects topology and current KPI evidence.
4. Provisional evidence produces `PARTIAL_RESULT`; missing evidence produces `WAITING_FOR_PERFORMANCE_DATA`.
5. A tenant-authorized `POST /v1/investigations/{investigation_id}/performance-events` accepts late KPI data with a caller-supplied event ID.
6. Event IDs are idempotent: a replay with the same payload has no second effect, while reuse with a different payload is rejected.
7. Final KPI data replaces the provisional row, recalculates findings, and transitions to `COMPLETED` or `HUMAN_REVIEW_REQUIRED` when degradation remains.
8. Unexpected background analysis failures are recorded as `FAILED`; state transitions and calculation versions are retained in history.
9. Production changes stay approval-gated and cannot be executed automatically.

The local prototype uses synthetic inventory/KPI seed data, SQLite for investigation/KPI/event/audit state, and FastAPI in-process background tasks. Records survive application restart, but background execution is not a durable queue and is not coordinated across multiple API workers. There are no production KPI connectors.

## Human approval workflow

1. A user with `change_planning` or `platform_admin` creates a proposal; the API stores it as `PENDING_HUMAN_APPROVAL` with `executed=false`.
2. The proposal is listed only within the requester's customer scope.
3. The Streamlit reviewer uses the `change_approver` role and a registered `X-Demo-User-ID`. The API resolves that user's role and customer from its local registry; submitted role/customer headers do not authorize a decision.
4. `POST /v1/change-proposals/{proposal_id}/approve` or `/reject` writes the decision, approver, timestamp, decision history, and audit record in one SQLite transaction.
5. Unknown users receive 401, known non-approvers receive 403, cross-tenant proposals return 404, and duplicate/final decisions return 409.
6. Approval records a human decision only. It never runs a network action, and `executed` remains false.

## Validation boundaries

- A real FastAPI restart preserved an investigation, its five state-history entries, the final KPI value, and the event ID; replay returned `duplicate=true`.
- The local fixture has two populated tenants (`CUST-A`, `CUST-B`). Isolation probes for `CUST-C` through `CUST-E` were denied because those tenants have no seeded entities.
- Approval and rejection now use the backend role policy and persist decision history. Validation confirms no proposal decision executes a network action.
- The initial response and topology latency measurements are local synthetic-dataset observations, not production SLOs.

## Determinism requirement

The workflow must never depend on an LLM to perform customer validation, KPI calculations or authorization checks. The LLM may only summarize structured evidence and explain recommended next steps.
