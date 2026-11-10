# Technical design

## Overview

The local prototype intentionally runs locally while preserving clear service boundaries. The authoritative architecture diagram distinguishes implemented local components from proposed production mappings in [architecture.md](architecture.md). Nothing in the target mapping is deployed by this project.

## Architecture diagram

See [architecture.md](architecture.md) for the two-view Mermaid diagram: implemented local prototype and proposed Google Cloud architecture. The proposed view is explicitly design-only.

## Design decisions

### Backend

- FastAPI provides the API layer and validation boundary.
- The service layer enforces business rules and tenant isolation.
- Synthetic data keeps the prototype local and deterministic.

### Data handling boundaries

- Local topology/inventory is a small synthetic Python fixture; KPI measurements and investigation/proposal state are persisted in SQLite.
- The target data model uses tenant-scoped relational inventory and temporal relationship records, with a graph store only if measured traversal requirements justify it.
- The target KPI pipeline uses versioned UTC windows, completeness/provisional states, and late-arrival recomputation; target-scale ingestion is not implemented locally.
- Investigation and proposal records have persistent state and history in the local prototype.

### Security

- The prototype distinguishes demo headers from production identity.
- Authorization is centralized in service logic, which keeps the local design understandable and production-mappable.

### UI and operations

- Streamlit provides a local operational dashboard for customer context, KPI comparisons and investigation review.
- The UI calls the same backend endpoints that the REST API uses.

## Production mapping (design only)

- Cloud Run: FastAPI services and MCP adapters
- Pub/Sub: investigation events and KPI completion events
- BigQuery: historical KPI analytics
- Cloud SQL PostgreSQL: inventory and relationship metadata
- Dataflow: ETL and KPI normalization
- IAM/OIDC: identity and role claims
- Cloud Logging: audit trail and monitoring
