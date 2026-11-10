# Telecom Network Intelligence — local prototype

This repository contains a local proof-of-concept for a telecom network intelligence platform built with FastAPI, synthetic inventory data, role-based access checks, and a Streamlit dashboard for operations and investigation review.

## Architecture summary

The local prototype models the following functional boundaries:

- Connection Factory: synthetic inventory fixtures only; no vendor adapters or ingestion jobs
- Inventory Service: customer, site, node, cell, service and transport records
- Topology Engine: bounded two-hop neighborhood traversal
- KPI Engine: baseline and incident KPI comparison with late-arrival handling
- Investigation workflow: deterministic investigation lifecycle and evidence review
- RBAC layer: tenant-aware role checks for demo-only role/customer headers plus a registry-backed approver user ID
- Human approval workflow: persistent approve/reject decisions with audit history; no production action execution
- Streamlit UI: dashboard and operational review for local demos
- SQLite: persistent investigation state, KPI measurements, performance-event IDs, transitions, proposals, decisions and audit records

## Local persistent storage

The API initializes a SQLite database at `data/network_intelligence.sqlite3`. The file is local runtime state and is excluded from Git. Set `NETWORK_INTELLIGENCE_DB` before starting FastAPI to use another database path. Synthetic KPI seed rows are inserted only when their tenant, cell, metric and window key is absent; late final measurements therefore remain intact after restart.

The database schema is created automatically. The relationship to Cloud SQL PostgreSQL, Pub/Sub and BigQuery is documented in [docs/data-model.md](docs/data-model.md). This prototype does not connect to or deploy on Google Cloud.

## Windows local setup

Run these commands from PowerShell in the project folder:

```powershell
cd "c:\Users\farha\OneDrive\Desktop\network_intelligence_submission"
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Start the FastAPI API locally

```powershell
cd "c:\Users\farha\OneDrive\Desktop\network_intelligence_submission"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the API docs at:

- http://127.0.0.1:8000/docs

## Start the Streamlit dashboard locally

```powershell
cd "c:\Users\farha\OneDrive\Desktop\network_intelligence_submission"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\streamlit.exe run app\streamlit_app.py --server.headless true --server.port 8501
```

Open the dashboard at:

- http://127.0.0.1:8501

## Demo API examples

```powershell
curl -H "X-Demo-Role: alarm_management" -H "X-Customer-ID: CUST-A" "http://127.0.0.1:8000/v1/topology/CELL-PUN-101?depth=2"
curl -H "X-Demo-Role: alarm_management" -H "X-Customer-ID: CUST-A" "http://127.0.0.1:8000/v1/kpis/CELL-PUN-101"
curl -X POST "http://127.0.0.1:8000/v1/investigations" -H "Content-Type: application/json" -H "X-Demo-Role: alarm_management" -H "X-Customer-ID: CUST-A" -d '{"affected_cells":["CELL-PUN-101","CELL-PUN-102"],"incident_time":"2026-11-10T10:05:00Z"}'
```

Change planning is available to `change_planning` and `platform_admin`. Approval and rejection require a known user ID with the `change_approver` role. Local approver IDs are `approver-cust-a` and `approver-cust-b`; decision requests use `X-Demo-User-ID` and do not accept caller-supplied tenant identity. The API routes are `GET /v1/change-proposals`, `POST /v1/change-proposals/{proposal_id}/approve`, and `POST /v1/change-proposals/{proposal_id}/reject`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Important design notes

- The `X-Demo-Role` and `X-Customer-ID` headers are intentionally demo-only and must not be considered production authentication.
- All customer data is synthetic and scoped to local demo workloads.
- The project intentionally keeps the local prototype deterministic and auditable.
- Production evolution would replace the demo identity model with verified OIDC/JWT claims and policy enforcement.

## Final validation snapshot

- Automated tests: 31 passed; one existing Starlette/httpx deprecation warning.
- SQLite restart check: an investigation, transition history, final KPI, event ID and audit records remained available after a separate FastAPI restart. Replaying the event returned `duplicate=true`.
- Tenant checks: `CUST-A` and `CUST-B` are the only populated synthetic tenants. `CUST-C`, `CUST-D`, and `CUST-E` were checked and denied access to those tenant resources.
- Performance on the local Windows prototype: 100 concurrent investigation POSTs returned 100 HTTP 200 responses (p50 1.4154s, p95 8.4078s); 100 sequential two-hop topology requests returned 100 HTTP 200 responses (p50 16.418ms, p95 28.407ms). These are not production capacity targets.
- Change proposals start pending. Approval and rejection persist approver identity, decision, timestamp and history, and remain `executed=false`.

See [docs/architecture.md](docs/architecture.md) for the architecture and design-only cloud mapping, and [docs/RBAC-matrix.md](docs/RBAC-matrix.md) for verified authorization boundaries.

The approver user registry and role headers are local demo authentication only. The approval workflow records a human decision but does not execute or connect to a real network operation.

## Submission documents

- [Requirement traceability matrix](docs/requirements-traceability.md)
- [Architecture diagrams and component mapping](docs/architecture.md)
- [Data model and persistence](docs/data-model.md)
- [RBAC and tenant isolation](docs/RBAC-matrix.md)
- [Agent and approval workflow](docs/agent-workflow.md)
- [API reference](docs/api-reference.md) and [machine-readable API contract](docs/api-contract.json)
- [Five-minute demo script](docs/demo-script.md)
- [Limitations and scope](docs/limitations.md)
- [Final submission checklist](docs/final-submission-checklist.md)

## Project deliverables

The repository includes the working FastAPI prototype, local synthetic data, RBAC checks, workflow logic, API contract, and the Streamlit dashboard.

Additional design notes are in the `docs/` folder.
