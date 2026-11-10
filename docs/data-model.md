# Data model and storage strategy

## Local prototype model

The local API uses SQLite at `data/network_intelligence.sqlite3` by default. Override the location with `NETWORK_INTELLIGENCE_DB`. Schema initialization is automatic, and synthetic KPI seed rows are inserted with `INSERT OR IGNORE` so a persisted late measurement is not replaced on restart. The logical entities are:

- Customer
- Site
- Node
- Cell
- Service
- Transport
- Relationship
- KPI record
- Investigation record
- Change proposal

Each record includes a `customer_id` or `tenant_id` field to enforce strict scoping.

Operational state is persisted in these SQLite tables:

- `investigations`: tenant, current status, timestamps and the API-compatible JSON record.
- `investigation_transitions`: append-only state transitions with event, timestamp and calculation version.
- `kpi_measurements`: measurements keyed by customer, cell, metric and window; late final data updates the matching provisional row.
- `performance_events`: unique event ID, tenant, investigation, canonical payload fingerprint and result for replay detection.
- `audit_records`: customer-scoped actor, action, resource, timestamp and structured details.
- `change_proposals`: tenant-owned proposal payload and current pending/approved/rejected status.
- `change_proposal_decisions`: one decision per tenant/proposal, with decision, approver user ID/role, timestamp, note, and an enforced `executed=0` value.

Every query for an investigation, KPI, transition or audit record includes the authenticated customer ID. Performance event writes first resolve the investigation in that same tenant. The event ID has a database uniqueness constraint and the service serializes local delivery handling.

## Cloud architecture mapping (design only)

No Google Cloud resources are created or used by this local project.

### Cloud SQL for PostgreSQL

Replace the SQLite connection/repository layer with a PostgreSQL repository using Cloud SQL. Keep the same ownership boundaries and tenant-scoped predicates; translate JSON record storage to `JSONB`, retain relational investigation and KPI columns, and use transactions for state changes, transition history, event deduplication and audit writes. Enforce tenant scope in application queries and add PostgreSQL row-level security as defense in depth. Use managed credentials and private connectivity in a future deployment.

### Pub/Sub

Replace FastAPI in-process background tasks with a Pub/Sub investigation-work topic. A worker consumes alarms and performance events, acknowledges only after a database transaction commits, and expects at-least-once delivery. Keep `event_id` unique in Cloud SQL so redelivery is idempotent; use bounded retries and a dead-letter topic for repeatedly failing events. The HTTP API can continue returning `RECEIVED` immediately after durable enqueueing.

### BigQuery

Export append-only KPI observations, event history and audit facts to BigQuery for long-range analytics, dashboards and cross-period trends. Partition by observation date and cluster on `customer_id` and cell/entity ID. Cloud SQL remains the authoritative source for current investigation status and event idempotency; BigQuery is analytical and is not used to authorize or mutate investigations.

## Relational schema recommendation

```sql
CREATE TABLE customer (
    customer_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE site (
    site_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    name VARCHAR(128) NOT NULL,
    version_ts TIMESTAMP NOT NULL,
    UNIQUE (customer_id, site_id)
);

CREATE TABLE node (
    node_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    name VARCHAR(128) NOT NULL,
    transport_id VARCHAR(64),
    version_ts TIMESTAMP NOT NULL
);

CREATE TABLE cell (
    cell_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    site_id VARCHAR(64) NOT NULL REFERENCES site(site_id),
    node_id VARCHAR(64) NOT NULL REFERENCES node(node_id),
    service_id VARCHAR(64),
    name VARCHAR(128) NOT NULL,
    version_ts TIMESTAMP NOT NULL
);

CREATE TABLE service (
    service_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    name VARCHAR(128) NOT NULL,
    type VARCHAR(32) NOT NULL,
    version_ts TIMESTAMP NOT NULL
);

CREATE TABLE relationship (
    relationship_id BIGSERIAL PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    source_id VARCHAR(64) NOT NULL,
    target_id VARCHAR(64) NOT NULL,
    relationship_type VARCHAR(32) NOT NULL,
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP NULL,
    source_system VARCHAR(64) NOT NULL,
    UNIQUE (customer_id, source_id, target_id, relationship_type, valid_from)
);

CREATE TABLE kpi_record (
    kpi_id BIGSERIAL PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    entity_id VARCHAR(64) NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    value NUMERIC(12,4) NOT NULL,
    status VARCHAR(32) NOT NULL,
    formula_version VARCHAR(32) NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    UNIQUE (customer_id, entity_id, metric_name, window_start, formula_version)
);

CREATE TABLE investigation (
    investigation_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customer(customer_id),
    incident_time TIMESTAMP NOT NULL,
    state VARCHAR(32) NOT NULL,
    completeness VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

## Why PostgreSQL

PostgreSQL is the best fit for:

- inventory and relationship records
- historical versions
- tenant-scoped constraints
- operational metadata
- transactional integrity for change proposals and investigation state

## Why BigQuery

BigQuery is ideal for:

- KPI history and large-scale performance data
- analytical joins and aggregated trend analysis
- time-series queries across millions of rows
- late-arriving data and partitioned event analysis

## Why graph database is optional

A graph database is only justified when the topology query workload becomes truly graph-centric and more complex than a relational graph adjacency model. For this local prototype, relational tables plus efficient adjacency queries are sufficient and simpler to operate.

## Indexing guidance

- Index `customer_id` on all tenant-scoped tables.
- Index `entity_id` and `metric_name` on KPI tables.
- Index `valid_from`, `valid_to` on relationships.
- Index `incident_time` and `state` on investigation tables.
- Use partitioning for KPI tables by date and customer.

## Runtime SQLite validation

The implemented local tables are `investigations`, `investigation_transitions`, `kpi_measurements`, `performance_events`, `audit_records`, `change_proposals`, and `change_proposal_decisions`. The event primary key is `(customer_id, event_id)`; KPI uniqueness is `(customer_id, cell_id, metric, window)`. Investigation transition and event rows reference an investigation using both `investigation_id` and `customer_id`. Proposal decisions use a unique `(proposal_id, customer_id)` constraint and foreign key, preventing a second decision for the same tenant-owned proposal.

The restart test creates an investigation and final KPI event, starts a separate Python process against the same SQLite file, and verifies the saved investigation/history, five transitions, recalculated KPI, event fingerprint/result, and audit records. The API also replays the event after process restart and returns `duplicate=true`.

Local isolation coverage checks `CUST-A` through `CUST-E`. Only `CUST-A` and `CUST-B` have seeded inventory/KPI data; the other three contexts are denied access and do not represent fully populated customer tenants. Approval restart tests verify the decision identity, timestamp, history, and non-execution flag survive a separate process reading the same SQLite file.
