# RBAC matrix and tenant isolation

## Roles

| Role | Topology read | KPI read | Incident investigation | Change proposal | Approve/reject | Audit access |
| --- | --- | --- | --- | --- | --- | --- |
| `alarm_management` | Yes | Yes | Yes | No | No | Records written; no read API |
| `performance_analysis` | Yes | Yes | Yes | No | No | Records written; no read API |
| `change_planning` | Yes | Yes | Yes | Yes | No | Records written; no read API |
| `change_approver` | Yes | Yes | No | No | Yes | Records written; no read API |
| `platform_admin` | Yes | Yes | Yes | Yes | No | Records written; no read API |

## Security principles

- Every data request must be scoped to the authenticated tenant.
- The approval endpoints resolve user, role, and customer from `X-Demo-User-ID`; they do not trust request-supplied role or customer headers for approval authorization.
- Other demo endpoints use `X-Demo-Role` and `X-Customer-ID`; these are caller-supplied simulation headers, not verified production credentials.
- A tenant may never read or modify another tenant's entity or investigation record.
- Authorization must be evaluated at every service boundary.

## Demo implementation

The local prototype uses demo headers for identity simulation:

- `X-Demo-Role`
- `X-Customer-ID`
- `X-Demo-User-ID` for proposal approval/rejection

These headers are used only for local demonstration and explicit security testing. They are not production authentication.

The registered approver IDs are `approver-cust-a` and `approver-cust-b`, each bound to `change_approver` and one customer. Known users without the approver role receive 403; unknown or missing user IDs receive 401. A valid approver for a different customer receives 404 for the proposal.

## Verified local scope

The role map contains four roles and the inventory fixture has two populated tenants, `CUST-A` and `CUST-B`. Isolation checks also probe `CUST-C`, `CUST-D`, and `CUST-E`; those contexts have no local inventory and receive 404 for customer-owned resources. They are not five populated customer datasets.

`change_planning` and `platform_admin` can submit proposals. They start as `PENDING_HUMAN_APPROVAL`. Only `change_approver` can approve or reject through the API. Duplicate/final decisions return 409. The decision record and audit history include approver identity, decision, timestamp, and `executed=false`.

No production action connector exists. Streamlit calls the same server-side decision endpoints and does not execute network changes.

Audit events are persisted per customer, but no audit-read API is exposed. The access column above describes this implementation rather than an intended future capability.

## Production recommendation

In production, use OIDC/OAuth2 claims from an identity provider and enforce policies with Open Policy Agent or a centralized authorization service. The same tenant-scoping logic should remain in the backend services.
