# MCP tool contract

> **Design-only contract:** no MCP server or adapter is implemented or running in this repository. REST remains the implemented interface; this document specifies a future adapter that must reuse the same backend logic.

The proposed MCP layer must not bypass identity checks, tenant scoping or change approval.

## Tool definitions

### get_topology_neighborhood
- Input: `entity_id`, `depth`, `customer_id`
- Output: bounded neighborhood, relationships and provenance
- Authorization: `topology:read`

### get_kpi_series
- Input: `entity_id`, `customer_id`, optional window filters
- Output: KPI series with statuses, completeness and formula version
- Authorization: `kpi:read`

### investigate_alarm
- Input: `customer_id`, `affected_cells`, `incident_time`
- Output: investigation ID, state, evidence and recommendation
- Authorization: `topology:read` + `kpi:read`

### get_investigation_status
- Input: `investigation_id`, `customer_id`
- Output: current state, updated timestamp and history
- Authorization: `kpi:read`

### propose_network_change
- Input: `customer_id`, `target_id`, `action`, `rationale`
- Output: proposal record and approval state
- Authorization: `change:propose`

## Security requirements

- MCP tools must call the same backend business services as REST endpoints.
- Tenancy must be validated before any read or write operation.
- Recommendation generation may summarize structured output but must not independently calculate KPI data or execute network changes.
- Approvals remain human-controlled even when the agent proposes actions.
