# Assumptions and scope

## Business assumptions

- 5 customers with strict data isolation.
- 25,000 network nodes.
- 250,000 cells.
- 2,000,000 network relationships.
- 50 million performance-counter records per day.
- Performance windows are measured in 15-minute intervals.
- KPI data may arrive up to 2 hours late.
- Inventory updates occur hourly.
- Up to 100 concurrent investigation requests.
- Two-hop topology lookups should target p95 latency below 2 seconds.
- Initial investigation response should target 30 seconds.
- Production changes require human approval.

## Synthetic data approach

The local prototype uses deterministic synthetic data to emulate telecom inventory, relationships and KPI behavior. This keeps the project runnable on a local laptop while validating role-based access, KPI completeness logic and investigation flow.

## Security assumptions

- Demo headers are not equivalent to production identity.
- All tenant isolation decisions should be enforced in backend services.
- Only the backend should decide authorization and data visibility.

## Production mapping

The local prototype is intentionally a simplified version of the target production design:

- Cloud Run for the backend and orchestration services
- Pub/Sub for event-driven investigation triggers and KPI completion events
- BigQuery for KPI analytics and historical trend analysis
- Cloud SQL PostgreSQL for inventory and tenant metadata
- Dataflow for batch and streaming transformations
- IAM/OIDC for identity and access control
- Cloud Logging for audit and incident monitoring
