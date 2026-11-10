# Five-Minute Technical Demo Script

## Before the demo

Use synthetic data only. For a fresh, reproducible investigation/KPI sequence, start FastAPI with a new ignored SQLite path:

```powershell
$env:NETWORK_INTELLIGENCE_DB = "$PWD\data\submission_demo.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, start Streamlit:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.headless true --server.port 8501
```

Open `http://127.0.0.1:8501` and `http://127.0.0.1:8000/docs`.

## Run of show

| Time | Demo action | What to point out |
| --- | --- | --- |
| 0:00-0:25 | Introduce the local prototype and architecture diagram. | FastAPI + Streamlit + SQLite; synthetic data; cloud components are proposed only. |
| 0:25-0:55 | Show the dashboard overview and tenant/role context. | Start as `CUST-A` / `alarm_management`; only two customer datasets are populated. |
| 0:55-1:20 | Review the topology graph for `CELL-PUN-101`. | Highlight the shared `TX-PUN-01` transport node; explain traversal is two-hop and fixture-backed. |
| 1:20-1:45 | Review KPI analytics. | Compare baseline with the provisional incident window and show completeness. |
| 1:45-2:15 | Submit an investigation for `CELL-PUN-101` with incident time `2026-11-10T10:05:00Z`. | Point out the immediate `RECEIVED` acknowledgment, then history transitions to `IN_PROGRESS` and `PARTIAL_RESULT`. |
| 2:15-2:40 | Open investigation history and agent timeline. | Show investigation ID, tenant, affected cell, timestamps, state, and provisional evidence. |
| 2:40-3:05 | Process the synthetic late KPI event using a unique event ID and final availability `98.75`. | Show recalculation, `FINAL_KPI`, calculation version update, and the final state. A duplicate replay is marked ignored. |
| 3:05-3:35 | Switch to `change_planning` and submit a proposal. | Show `PENDING_HUMAN_APPROVAL` and `executed=false`. |
| 3:35-4:10 | Switch to `change_approver` and approve the proposal. | The registered `approver-cust-a` identity is attached; show persisted decision history and that execution remains false. |
| 4:10-4:35 | Create a second proposal and reject it as the approver. | Show the rejected status and rejection note in decision history. |
| 4:35-5:00 | Use Swagger to point out approve/reject routes and summarize the guardrails. | Unknown users get 401, known non-approvers 403, cross-tenant proposals 404, final/duplicate decisions 409. No network operation executes. |

## Optional isolation check

In Swagger, query `GET /v1/kpis/CELL-PUN-101` with `X-Customer-ID: CUST-B`; it should return 404. The tests also probe `CUST-C`, `CUST-D`, and `CUST-E`, which have no seeded inventory.

## Demo caveats

A clean SQLite path ensures the incident KPI starts provisional. If reusing an existing database, KPI measurements and proposals persist by design. Audit records are stored, but there is no audit-read API; display the proposal decision history and audit summary in the dashboard instead of claiming a full audit browser.
