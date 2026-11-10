# Limitations and Scope

## Local prototype limits

- **Synthetic coverage:** the fixture contains two populated customer datasets (`CUST-A`, `CUST-B`), not five complete tenants. `CUST-C` through `CUST-E` are denial/isolation probes only.
- **Inventory ingestion:** Connection Factory behavior is represented by static synthetic fixtures; there are no vendor connectors, inventory jobs, or hourly updates.
- **Topology storage:** bounded traversal uses Python fixture relationships. No graph database is installed or queried.
- **Authorization:** general API identities use demo role/customer headers. Approver identities are a small static local registry; there is no OIDC/JWT identity provider or OPA deployment.
- **Agents:** the investigation workflow is deterministic service logic, not an LLM-based agent system or LangGraph graph.
- **Async execution:** `BackgroundTasks` run inside the API process. They are not durable, do not coordinate across multiple workers, and can be lost on process termination.
- **Database:** SQLite is local single-host storage. There is no multi-instance Cloud SQL configuration or production migration/backup plan.
- **Analytics and event bus:** BigQuery and Pub/Sub are documented architecture mappings only. There are no cloud exports, Pub/Sub topics, workers, retries, or dead-letter queues.
- **MCP:** tool contracts are documented, but no MCP server/adapter is running.
- **Human approval:** approve/reject decisions and audit records persist, but no network executor exists. `executed` is constrained to false.
- **Audit access:** audit rows are persisted, but no API endpoint for browsing the audit table is implemented; proposal decision history is available through proposal list responses.
- **Performance:** the 100-request and topology timings use a very small local synthetic dataset. They are not a capacity test for the assignment's target inventory/KPI volumes or a production SLO.
- **Browser automation:** Streamlit flows were manually exercised; the automated suite primarily covers API and persistence behavior.

## Production blockers

Before production use, replace demo identity, use durable queue/workers, deploy a supported relational and topology store, define operational OPA/IAM policies, implement resilient event transactions and migrations, build observability/backups, validate target-scale performance, and connect only through a separately approved and safety-tested action executor.

This assignment has not been deployed to Google Cloud and is not production-ready.
