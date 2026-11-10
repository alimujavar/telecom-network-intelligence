from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("NETWORK_INTELLIGENCE_DB", PROJECT_ROOT / "data" / "network_intelligence.sqlite3"))


def _connect() -> sqlite3.Connection:
    path = Path(DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def initialize(seed_kpis: dict[str, list[dict[str, Any]]], entities: dict[str, dict[str, Any]]) -> None:
    with _transaction() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                record_json TEXT NOT NULL,
                UNIQUE (investigation_id, customer_id)
            );
            CREATE INDEX IF NOT EXISTS ix_investigations_customer_updated
                ON investigations (customer_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS investigation_transitions (
                transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                previous_state TEXT,
                state TEXT NOT NULL,
                event TEXT NOT NULL,
                transitioned_at TEXT NOT NULL,
                calculation_version TEXT NOT NULL,
                FOREIGN KEY (investigation_id, customer_id)
                    REFERENCES investigations (investigation_id, customer_id)
            );
            CREATE INDEX IF NOT EXISTS ix_transitions_customer_investigation
                ON investigation_transitions (customer_id, investigation_id, transition_id);

            CREATE TABLE IF NOT EXISTS kpi_measurements (
                customer_id TEXT NOT NULL,
                cell_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                window TEXT NOT NULL,
                value REAL NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (customer_id, cell_id, metric, window)
            );
            CREATE INDEX IF NOT EXISTS ix_kpi_customer_cell_window
                ON kpi_measurements (customer_id, cell_id, window);

            CREATE TABLE IF NOT EXISTS performance_events (
                event_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                fingerprint_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (customer_id, event_id),
                FOREIGN KEY (investigation_id, customer_id)
                    REFERENCES investigations (investigation_id, customer_id)
            );

            CREATE TABLE IF NOT EXISTS audit_records (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_audit_customer_created
                ON audit_records (customer_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS change_proposals (
                proposal_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                PRIMARY KEY (proposal_id, customer_id)
            );
            CREATE INDEX IF NOT EXISTS ix_change_proposals_customer_status
                ON change_proposals (customer_id, status, created_at DESC);

            CREATE TABLE IF NOT EXISTS change_proposal_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
                decided_by TEXT NOT NULL,
                approver_role TEXT NOT NULL,
                decided_at TEXT NOT NULL,
                note TEXT,
                executed INTEGER NOT NULL DEFAULT 0 CHECK (executed = 0),
                UNIQUE (proposal_id, customer_id),
                FOREIGN KEY (proposal_id, customer_id)
                    REFERENCES change_proposals (proposal_id, customer_id)
            );
            """
        )
        event_primary_key = [row["name"] for row in connection.execute("PRAGMA table_info(performance_events)") if row["pk"]]
        if event_primary_key == ["event_id"]:
            connection.execute(
                """CREATE TABLE performance_events_v2 (
                       event_id TEXT NOT NULL,
                       customer_id TEXT NOT NULL,
                       investigation_id TEXT NOT NULL,
                       fingerprint_json TEXT NOT NULL,
                       response_json TEXT NOT NULL,
                       created_at TEXT NOT NULL,
                       PRIMARY KEY (customer_id, event_id),
                       FOREIGN KEY (investigation_id, customer_id)
                           REFERENCES investigations (investigation_id, customer_id)
                   )"""
            )
            connection.execute(
                """INSERT INTO performance_events_v2
                   SELECT event_id, customer_id, investigation_id, fingerprint_json, response_json, created_at
                   FROM performance_events"""
            )
            connection.execute("DROP TABLE performance_events")
            connection.execute("ALTER TABLE performance_events_v2 RENAME TO performance_events")
        for cell_id, rows in seed_kpis.items():
            customer_id = entities[cell_id]["customer_id"]
            for row in rows:
                connection.execute(
                    """INSERT OR IGNORE INTO kpi_measurements
                       (customer_id, cell_id, metric, window, value, status, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (customer_id, cell_id, row["metric"], row["window"], row["value"], row["status"], row["observed_at"]),
                )


def add_audit_record(customer_id: str, actor_role: str, action: str, resource_id: str,
                     created_at: str, details: dict[str, Any]) -> None:
    with _transaction() as connection:
        connection.execute(
            """INSERT INTO audit_records (customer_id, actor_role, action, resource_id, created_at, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (customer_id, actor_role, action, resource_id, created_at, _json(details)),
        )


def create_investigation(record: dict[str, Any], actor_role: str) -> None:
    with _transaction() as connection:
        connection.execute(
            """INSERT INTO investigations
               (investigation_id, customer_id, status, created_at, updated_at, record_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["investigation_id"], record["customer_id"], record["status"], record["created_at"],
             record["updated_at"], _json(record)),
        )
        for transition in record.get("history", []):
            connection.execute(
                """INSERT INTO investigation_transitions
                   (investigation_id, customer_id, previous_state, state, event, transitioned_at, calculation_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (record["investigation_id"], record["customer_id"], None, transition["state"], transition["event"],
                 transition["timestamp"], transition["calculation_version"]),
            )
        connection.execute(
            """INSERT INTO audit_records (customer_id, actor_role, action, resource_id, created_at, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["customer_id"], actor_role, "investigation_created", record["investigation_id"],
             record["created_at"], _json({"affected_cells": record["affected_cells"], "status": record["status"]})),
        )


def get_investigation(investigation_id: str, customer_id: str) -> dict[str, Any] | None:
    with _transaction() as connection:
        row = connection.execute(
            "SELECT record_json FROM investigations WHERE investigation_id = ? AND customer_id = ?",
            (investigation_id, customer_id),
        ).fetchone()
    return json.loads(row["record_json"]) if row else None


def update_investigation(record: dict[str, Any]) -> None:
    with _transaction() as connection:
        cursor = connection.execute(
            """UPDATE investigations SET status = ?, updated_at = ?, record_json = ?
               WHERE investigation_id = ? AND customer_id = ?""",
            (record["status"], record["updated_at"], _json(record), record["investigation_id"], record["customer_id"]),
        )
        if cursor.rowcount != 1:
            raise LookupError("Investigation not found")


def save_transition(record: dict[str, Any], previous_state: str, event: str,
                    actor_role: str = "system") -> None:
    transition = record["history"][-1]
    with _transaction() as connection:
        cursor = connection.execute(
            """UPDATE investigations SET status = ?, updated_at = ?, record_json = ?
               WHERE investigation_id = ? AND customer_id = ?""",
            (record["status"], record["updated_at"], _json(record), record["investigation_id"], record["customer_id"]),
        )
        if cursor.rowcount != 1:
            raise LookupError("Investigation not found")
        connection.execute(
            """INSERT INTO investigation_transitions
               (investigation_id, customer_id, previous_state, state, event, transitioned_at, calculation_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record["investigation_id"], record["customer_id"], previous_state, record["status"], event,
             transition["timestamp"], record["calculation_version"]),
        )
        connection.execute(
            """INSERT INTO audit_records (customer_id, actor_role, action, resource_id, created_at, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["customer_id"], actor_role, f"investigation_{event}", record["investigation_id"],
             transition["timestamp"], _json({"from": previous_state, "to": record["status"]})),
        )


def get_transitions(investigation_id: str, customer_id: str) -> list[dict[str, Any]]:
    with _transaction() as connection:
        rows = connection.execute(
            """SELECT previous_state, state, event, transitioned_at, calculation_version
               FROM investigation_transitions WHERE investigation_id = ? AND customer_id = ?
               ORDER BY transition_id""",
            (investigation_id, customer_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_kpi_measurements(customer_id: str, cell_id: str) -> list[dict[str, Any]]:
    with _transaction() as connection:
        rows = connection.execute(
            """SELECT metric, window, value, status, observed_at FROM kpi_measurements
               WHERE customer_id = ? AND cell_id = ? ORDER BY window, metric""",
            (customer_id, cell_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_kpi_measurement(customer_id: str, cell_id: str, metric: str, window: str) -> dict[str, Any] | None:
    with _transaction() as connection:
        row = connection.execute(
            """SELECT metric, window, value, status, observed_at FROM kpi_measurements
               WHERE customer_id = ? AND cell_id = ? AND metric = ? AND window = ?""",
            (customer_id, cell_id, metric, window),
        ).fetchone()
    return dict(row) if row else None


def upsert_kpi_measurement(customer_id: str, cell_id: str, measurement: dict[str, Any]) -> None:
    with _transaction() as connection:
        connection.execute(
            """INSERT INTO kpi_measurements
               (customer_id, cell_id, metric, window, value, status, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(customer_id, cell_id, metric, window) DO UPDATE SET
                   value = excluded.value, status = excluded.status, observed_at = excluded.observed_at""",
            (customer_id, cell_id, measurement["metric"], measurement["window"], measurement["value"],
             measurement["status"], measurement["observed_at"]),
        )


def delete_kpi_measurement(customer_id: str, cell_id: str, metric: str, window: str) -> None:
    with _transaction() as connection:
        connection.execute(
            "DELETE FROM kpi_measurements WHERE customer_id = ? AND cell_id = ? AND metric = ? AND window = ?",
            (customer_id, cell_id, metric, window),
        )


def get_performance_event(event_id: str, customer_id: str) -> dict[str, Any] | None:
    with _transaction() as connection:
        row = connection.execute(
            """SELECT customer_id, investigation_id, fingerprint_json, response_json
               FROM performance_events WHERE event_id = ? AND customer_id = ?""",
            (event_id, customer_id),
        ).fetchone()
    if not row:
        return None
    return {
        "customer_id": row["customer_id"],
        "investigation_id": row["investigation_id"],
        "fingerprint": json.loads(row["fingerprint_json"]),
        "response": json.loads(row["response_json"]),
    }


def save_performance_event(event_id: str, customer_id: str, investigation_id: str,
                           fingerprint: dict[str, Any], response: dict[str, Any], created_at: str) -> None:
    with _transaction() as connection:
        connection.execute(
            """INSERT INTO performance_events
               (event_id, customer_id, investigation_id, fingerprint_json, response_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, customer_id, investigation_id, _json(fingerprint), _json(response), created_at),
        )


def get_audit_records(customer_id: str) -> list[dict[str, Any]]:
    with _transaction() as connection:
        rows = connection.execute(
            """SELECT audit_id, customer_id, actor_role, action, resource_id, created_at, details_json
               FROM audit_records WHERE customer_id = ? ORDER BY audit_id""",
            (customer_id,),
        ).fetchall()
    return [{**dict(row), "details": json.loads(row["details_json"])} for row in rows]


def create_change_proposal(record: dict[str, Any], actor_role: str) -> None:
    with _transaction() as connection:
        connection.execute(
            """INSERT INTO change_proposals
               (proposal_id, customer_id, status, created_at, updated_at, proposal_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["proposal_id"], record["customer_id"], record["status"], record["created_at"],
             record["updated_at"], _json(record)),
        )
        connection.execute(
            """INSERT INTO audit_records (customer_id, actor_role, action, resource_id, created_at, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["customer_id"], actor_role, "change_proposal_created", record["proposal_id"],
             record["created_at"], _json({"target_id": record["target_id"], "status": record["status"]})),
        )


def get_change_proposal(proposal_id: str, customer_id: str) -> dict[str, Any] | None:
    with _transaction() as connection:
        row = connection.execute(
            "SELECT proposal_json FROM change_proposals WHERE proposal_id = ? AND customer_id = ?",
            (proposal_id, customer_id),
        ).fetchone()
    return json.loads(row["proposal_json"]) if row else None


def list_change_proposals(customer_id: str) -> list[dict[str, Any]]:
    with _transaction() as connection:
        rows = connection.execute(
            """SELECT proposal_json FROM change_proposals
               WHERE customer_id = ? ORDER BY created_at DESC, proposal_id""",
            (customer_id,),
        ).fetchall()
    return [json.loads(row["proposal_json"]) for row in rows]


def decide_change_proposal(proposal_id: str, customer_id: str, decision: str, decided_by: str,
                           approver_role: str, decided_at: str, note: str | None = None) -> dict[str, Any]:
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Invalid approval decision")
    with _transaction() as connection:
        row = connection.execute(
            "SELECT proposal_json FROM change_proposals WHERE proposal_id = ? AND customer_id = ?",
            (proposal_id, customer_id),
        ).fetchone()
        if not row:
            raise LookupError("Change proposal not found")
        record = json.loads(row["proposal_json"])
        if record["status"] != "PENDING_HUMAN_APPROVAL":
            raise ValueError("Change proposal already has a final decision")

        record["status"] = "APPROVED_BY_HUMAN_REVIEWER" if decision == "APPROVED" else "REJECTED_BY_HUMAN_REVIEWER"
        record["updated_at"] = decided_at
        record["approval_decision"] = decision
        record["approver_role"] = approver_role
        record["decided_by"] = decided_by
        record["approved_by"] = decided_by if decision == "APPROVED" else None
        record["approval_timestamp"] = decided_at
        record["executed"] = False
        record.setdefault("decision_history", []).append({
            "decision": decision,
            "decided_by": decided_by,
            "approver_role": approver_role,
            "timestamp": decided_at,
            "note": note,
            "executed": False,
        })

        cursor = connection.execute(
            """UPDATE change_proposals SET status = ?, updated_at = ?, proposal_json = ?
               WHERE proposal_id = ? AND customer_id = ? AND status = 'PENDING_HUMAN_APPROVAL'""",
            (record["status"], decided_at, _json(record), proposal_id, customer_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Change proposal already has a final decision")
        connection.execute(
            """INSERT INTO change_proposal_decisions
               (proposal_id, customer_id, decision, decided_by, approver_role, decided_at, note, executed)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (proposal_id, customer_id, decision, decided_by, approver_role, decided_at, note),
        )
        connection.execute(
            """INSERT INTO audit_records (customer_id, actor_role, action, resource_id, created_at, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (customer_id, approver_role, f"change_proposal_{decision.lower()}", proposal_id,
             decided_at, _json({"decided_by": decided_by, "decision": decision, "executed": False})),
        )
    return record