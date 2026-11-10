from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BACKEND_URL = "http://127.0.0.1:8000"
CUSTOMERS = ["CUST-A", "CUST-B"]
ROLES = ["alarm_management", "performance_analysis", "change_planning", "change_approver", "platform_admin"]
ROLE_PERMISSIONS = {
    "alarm_management": ["topology:read", "kpi:read", "incident:propose"],
    "performance_analysis": ["topology:read", "kpi:read", "analysis:export"],
    "change_planning": ["topology:read", "kpi:read", "change:read", "change:simulate", "change:propose"],
    "change_approver": ["topology:read", "kpi:read", "change:read", "change:approve"],
    "platform_admin": ["topology:read", "kpi:read", "incident:propose", "change:read", "change:simulate", "change:propose", "admin:write"],
}
DEMO_APPROVER_IDS = {"CUST-A": "approver-cust-a", "CUST-B": "approver-cust-b"}
CELL_OPTIONS = ["CELL-PUN-101", "CELL-PUN-102", "CELL-MUM-201"]

st.set_page_config(page_title="Telecom Network Intelligence", layout="wide")

if "investigations" not in st.session_state:
    st.session_state.investigations = []
if "latest_event_result" not in st.session_state:
    st.session_state.latest_event_result = None
if "customer_id" not in st.session_state:
    st.session_state.customer_id = "CUST-A"
if "role" not in st.session_state:
    st.session_state.role = "alarm_management"


def build_headers(extra: Dict[str, str] | None = None) -> Dict[str, str]:
    headers = {
        "X-Demo-Role": st.session_state.role,
        "X-Customer-ID": st.session_state.customer_id,
    }
    if st.session_state.role == "change_approver":
        headers["X-Demo-User-ID"] = DEMO_APPROVER_IDS.get(st.session_state.customer_id, "unknown-demo-user")
    if extra:
        headers.update(extra)
    return headers


def api_request(method: str, path: str, *, json_body: Dict[str, Any] | None = None) -> Any:
    request_headers = build_headers({"Content-Type": "application/json"} if json_body is not None else {})
    try:
        response = httpx.request(
            method,
            f"{BACKEND_URL}{path}",
            headers=request_headers,
            json=json_body,
            timeout=10,
        )
    except httpx.RequestError as exc:
        raise RuntimeError(f"Backend request failed: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"{response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Backend returned invalid JSON") from exc


@st.cache_data(ttl=30)
def fetch_health() -> Dict[str, Any]:
    return httpx.get(f"{BACKEND_URL}/health", timeout=10).json()


@st.cache_data(ttl=30)
def fetch_topology(entity_id: str) -> Dict[str, Any]:
    return api_request("GET", f"/v1/topology/{entity_id}?depth=2")


@st.cache_data(ttl=30)
def fetch_kpis(entity_id: str) -> Dict[str, Any]:
    return api_request("GET", f"/v1/kpis/{entity_id}")


st.title("Telecom Network Intelligence Dashboard")
st.caption("Synthetic local prototype for network investigations, KPI validation and tenant-scoped workflows.")

with st.sidebar:
    st.header("Tenant and agent context")
    st.session_state.customer_id = st.selectbox("Demo customer", CUSTOMERS, index=0)
    st.session_state.role = st.selectbox("Agent role", ROLES, index=0)
    selected_cell = st.selectbox("Affected cell", CELL_OPTIONS, index=0)
    st.write("Current tenant:", st.session_state.customer_id)
    if st.session_state.role == "change_approver":
        st.write("Current demo approver:", DEMO_APPROVER_IDS.get(st.session_state.customer_id, "Unconfigured"))
    st.write("Current permissions:")
    st.json(ROLE_PERMISSIONS[st.session_state.role])

    if st.button("Refresh backend data"):
        st.cache_data.clear()
        st.rerun()

try:
    health = fetch_health()
    topology = fetch_topology(selected_cell)
    kpis = fetch_kpis(selected_cell)
except Exception as exc:  # pragma: no cover - UI guard for offline backend
    st.error(f"Unable to load backend data: {exc}")
    st.stop()

st.subheader("Dashboard overview")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Customers", len(CUSTOMERS))
col2.metric("Network nodes", len(topology.get("nodes", [])))
col3.metric("Network cells", len(CELL_OPTIONS))
col4.metric("Relationships", len(topology.get("relationships", [])))
tenant_investigations = [
    item for item in st.session_state.investigations
    if item.get("customer_id") == st.session_state.customer_id
]
col5.metric("Active investigations", len(tenant_investigations))

st.subheader("Investigation request")
with st.form("investigation_form"):
    affected_cells = st.multiselect("Affected cells", CELL_OPTIONS, default=[selected_cell])
    submitted = st.form_submit_button("Run investigation")
    if submitted:
        payload = {"affected_cells": affected_cells, "incident_time": "2026-11-10T10:05:00Z"}
        try:
            response = api_request("POST", "/v1/investigations", json_body=payload)
            required_fields = (
                "investigation_id", "customer_id", "affected_cells", "status",
                "created_at", "updated_at", "evidence_completeness",
                "topology_snapshot_id", "recommendations",
            )
            if not isinstance(response, dict):
                raise RuntimeError("Backend returned an unexpected investigation response")
            missing_fields = [field for field in required_fields if field not in response]
            if missing_fields:
                raise RuntimeError(f"Backend response is missing fields: {', '.join(missing_fields)}")
            st.session_state.investigations.insert(0, {
                "investigation_id": response["investigation_id"],
                "customer_id": response["customer_id"],
                "affected_cells": response["affected_cells"],
                "state": response["status"],
                "status": response["status"],
                "created_at": response["created_at"],
                "updated_at": response["updated_at"],
                "completeness": response["evidence_completeness"],
                "history": response.get("history", []),
            })
            st.success(f"Investigation {response['investigation_id']} started with status {response['status']}")
            st.json(response)
        except Exception as exc:
            st.error(f"Investigation request failed: {exc}")

tenant_investigations = [
    item for item in st.session_state.investigations
    if item.get("customer_id") == st.session_state.customer_id
]

st.subheader("Topology")
with st.container():
    topology_nodes = topology.get("nodes", [])
    topology_edges = topology.get("relationships", [])
    graph = nx.DiGraph()
    for node in topology_nodes:
        graph.add_node(node["id"], label=node["id"], type=node["type"], customer_id=node.get("customer_id"), name=node.get("name"))
    for edge in topology_edges:
        graph.add_edge(edge["from"], edge["to"], type=edge["type"])

    positions = nx.spring_layout(graph, seed=42)
    node_x = []
    node_y = []
    node_text = []
    node_color = []
    node_size = []
    for node_id, node_attrs in graph.nodes(data=True):
        x0, y0 = positions[node_id]
        node_x.append(x0)
        node_y.append(y0)
        node_text.append(f"{node_attrs.get('label')}<br>{node_attrs.get('type')}")
        if node_id == selected_cell:
            node_color.append("#ff4b4b")
            node_size.append(28)
        elif node_attrs.get("type") == "transport":
            node_color.append("#f9c74f")
            node_size.append(22)
        elif node_attrs.get("type") == "site":
            node_color.append("#90be6d")
            node_size.append(20)
        else:
            node_color.append("#58a6ff")
            node_size.append(18)

    edge_x = []
    edge_y = []
    for source, target in graph.edges():
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, line=dict(width=2, color="#7f8c8d"), hoverinfo="none", mode="lines"))
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=[n for n in graph.nodes()],
            textposition="top center",
            marker=dict(size=node_size, color=node_color, line=dict(width=2, color="white")),
            hovertemplate="<b>%{text}</b><extra></extra>",
        )
    )
    fig.update_layout(title="Two-hop network topology view", showlegend=False, xaxis_visible=False, yaxis_visible=False, template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

    st.write("Topology root:", selected_cell)
    st.json({"nodes": topology_nodes, "relationships": topology_edges})

st.subheader("KPI analytics")
series = kpis.get("series", [])
if series:
    df = pd.DataFrame(series)
    availability = df[df["metric"] == "availability_pct"].copy()
    if not availability.empty:
        availability["window_order"] = availability["window"].map({"09:45-10:00Z": 0, "10:00-10:15Z": 1, "10:15-10:30Z": 2})
        availability = availability.sort_values("window_order")
        fig_kpi = px.line(
            availability,
            x="window",
            y="value",
            color="status",
            markers=True,
            title=f"Availability for {selected_cell}",
        )
        st.plotly_chart(fig_kpi, use_container_width=True)
    st.write("KPI completeness:", kpis.get("completeness"))
    st.write("Formula version:", kpis.get("formula_version"))
    st.dataframe(df)
else:
    st.info("No KPI records found for the selected cell.")

st.subheader("Investigation history")
if tenant_investigations:
    if st.button("Refresh investigation statuses"):
        for item in tenant_investigations:
            try:
                current = api_request("GET", f"/v1/investigations/{item['investigation_id']}/status")
                item.update({
                    "state": current["state"],
                    "status": current["status"],
                    "updated_at": current["updated_at"],
                    "completeness": current["evidence_completeness"],
                    "history": current["history"],
                })
            except Exception as exc:
                st.error(f"Unable to refresh {item['investigation_id']}: {exc}")

    history_df = pd.DataFrame(tenant_investigations)
    st.dataframe(history_df[["investigation_id", "customer_id", "affected_cells", "state", "created_at", "completeness", "status"]])
    selected_inv = st.selectbox("Open investigation detail", history_df["investigation_id"].tolist(), index=0)
    inv_detail = next(item for item in st.session_state.investigations if item["investigation_id"] == selected_inv)
    if inv_detail.get("history"):
        timeline_df = pd.DataFrame(inv_detail["history"])
        st.subheader("Agent execution timeline")
        st.dataframe(timeline_df)
    latest_event = st.session_state.latest_event_result
    if latest_event and latest_event["investigation_id"] == selected_inv:
        replay_label = " (duplicate event ignored)" if latest_event["duplicate"] else ""
        st.success(f"Event {latest_event['event_id']} processed: {latest_event['status']}{replay_label}")
        st.json(latest_event)

    with st.form("late_kpi_event_form"):
        st.subheader("Late KPI event")
        event_cell = st.selectbox("Event cell", inv_detail["affected_cells"])
        event_id = st.text_input("Event ID", value=f"late-kpi-{selected_inv}")
        event_value = st.number_input("Final availability (%)", min_value=0.0, max_value=100.0, value=98.75, step=0.05)
        event_submitted = st.form_submit_button("Process synthetic KPI event")
        if event_submitted:
            try:
                event_result = api_request(
                    "POST",
                    f"/v1/investigations/{selected_inv}/performance-events",
                    json_body={
                        "event_id": event_id,
                        "cell_id": event_cell,
                        "metric": "availability_pct",
                        "window": "10:00-10:15Z",
                        "value": event_value,
                        "observed_at": "2026-11-10T10:30:00Z",
                    },
                )
                inv_detail.update({
                    "state": event_result["state"],
                    "status": event_result["status"],
                    "updated_at": event_result["updated_at"],
                    "completeness": event_result["evidence_completeness"],
                    "history": event_result["history"],
                })
                st.session_state.latest_event_result = event_result
                st.rerun()
            except Exception as exc:
                st.error(f"KPI event processing failed: {exc}")
else:
    st.info("No investigations have been created yet. Use the investigation form above to start one.")

st.subheader("Change planning")
if st.session_state.role in {"change_planning", "platform_admin"}:
    with st.form("change_form"):
        target_options = (
            ["NODE-NOK-02", "SITE-MUM-02"] if st.session_state.customer_id == "CUST-B"
            else ["NODE-ERIC-01", "TX-PUN-01", "SITE-PUN-01"]
        )
        target_id = st.selectbox("Target entity", target_options)
        action = st.text_input("Network action", value="Restart transport path after validation")
        rationale = st.text_area("Rationale", value="Validate transport impact before the proposal is reviewed.")
        if st.form_submit_button("Submit change proposal"):
            try:
                response = api_request(
                    "POST",
                    "/v1/change-proposals",
                    json_body={"target_id": target_id, "action": action, "rationale": rationale},
                )
                st.success(f"Proposal submitted. Status: {response['status']}")
            except Exception as exc:
                st.error(f"Proposal submission failed: {exc}")

if st.session_state.role in {"change_planning", "change_approver", "platform_admin"}:
    try:
        proposals = api_request("GET", "/v1/change-proposals")
        if proposals:
            st.dataframe(pd.DataFrame(proposals)[[
                "proposal_id", "customer_id", "target_id", "action", "status", "created_at", "executed"
            ]])
            selected_proposal_id = st.selectbox(
                "Open proposal", [proposal["proposal_id"] for proposal in proposals]
            )
            selected_proposal = next(item for item in proposals if item["proposal_id"] == selected_proposal_id)
            st.json(selected_proposal)
            decisions = selected_proposal.get("decision_history", [])
            if decisions:
                st.subheader("Decision history")
                st.dataframe(pd.DataFrame(decisions))
            if selected_proposal["status"] == "PENDING_HUMAN_APPROVAL":
                if st.session_state.role == "change_approver":
                    approve_col, reject_col = st.columns(2)
                    with approve_col:
                        if st.button("Approve proposal", key=f"approve-{selected_proposal_id}"):
                            response = api_request(
                                "POST", f"/v1/change-proposals/{selected_proposal_id}/approve",
                                json_body={"note": "Approved in local review"},
                            )
                            st.success(f"Proposal approved by {response['decided_by']}; no network action executed.")
                            st.rerun()
                    with reject_col:
                        if st.button("Reject proposal", key=f"reject-{selected_proposal_id}"):
                            response = api_request(
                                "POST", f"/v1/change-proposals/{selected_proposal_id}/reject",
                                json_body={"note": "Rejected in local review"},
                            )
                            st.success(f"Proposal rejected by {response['decided_by']}; no network action executed.")
                            st.rerun()
                else:
                    st.info("This proposal is pending review by a designated approver.")
        else:
            st.info("No change proposals exist for this customer.")
    except Exception as exc:
        st.error(f"Unable to load change proposals: {exc}")

st.subheader("Audit and monitoring")
summary = {
    "health": health,
    "customer_scope": st.session_state.customer_id,
    "role": st.session_state.role,
    "permissions": ROLE_PERMISSIONS[st.session_state.role],
    "topology_snapshot": topology.get("provenance", {}).get("snapshot_id", "N/A"),
    "kpi_status": kpis.get("completeness", "UNAVAILABLE"),
}
st.json(summary)
