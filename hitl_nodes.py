from datetime import datetime, timezone
import json
import uuid
from typing import Literal
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

class HumanDecision(BaseModel):
    action: Literal["approve", "reject", "modify_amount"]
    approved_amount_usd: float | None = Field(default=None, ge=0.0)
    reviewer_note: str = Field(min_length=3)
    reviewer_id: str = "tier2_supervisor"

def human_approval_node(state: dict) -> Command:
    eval_res = state["deterministic_eval"]
    proposal = state["proposal"]
    # Purely JSON-serializable payload; zero DB mutations before interrupt()
    decision: HumanDecision = interrupt(
        {
            "ticket_id": state["ticket_id"],
            "proposed_action": proposal["proposed_action"],
            "requested_refund_usd": eval_res["requested_refund_usd"],
            "max_refundable_usd": eval_res["max_refundable_usd"],
            "sla_status": eval_res["sla_status"],
            "policy_citations": proposal["policy_citations"],
            "reason_code": eval_res["reason_code"],
            "rationale": proposal["rationale"],
        },
        response_schema=HumanDecision,
    )
    return Command(
        update={
            "approval_decision": decision.model_dump(),
            "audit_events": [f"HITL:{decision.action} by {decision.reviewer_id}"],
        },
        goto="execute_write" if decision.action in ("approve", "modify_amount") else "finalize_rejection",
    )

def execute_write_node(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    if runtime.context.actor_role == "readonly_viewer":
        raise PermissionError("Write blocked: readonly_viewer cannot mutate operational DB.")

    conn = runtime.context.ops_conn
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    decision = state.get("approval_decision") or {"action": "auto_approve", "reviewer_id": "deterministic_engine"}
    amount = (
        decision.get("approved_amount_usd")
        if decision.get("action") == "modify_amount" and decision.get("approved_amount_usd") is not None
        else state["deterministic_eval"]["requested_refund_usd"]
    )
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("BEGIN IMMEDIATE")
    try:
        order = conn.execute(
            "SELECT status, amount_usd FROM orders WHERE order_id = ?",
            (state["order_id"],),
        ).fetchone()
        if not order or order["status"] == "refunded":
            conn.rollback()
            return {"execution_result": "ABORTED_ALREADY_REFUNDED"}
        if amount > order["amount_usd"]:
            conn.rollback()
            return {"execution_result": "ABORTED_EXCEEDS_ORDER_TOTAL"}

        refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(
            "INSERT INTO refund_ledger VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                refund_id,
                state["ticket_id"],
                state["order_id"],
                amount,
                "hitl_approved" if state.get("approval_decision") else "auto_approved",
                decision.get("reviewer_id", "deterministic_engine"),
                now,
            ),
        )
        conn.execute("UPDATE orders SET status = 'refunded' WHERE order_id = ?", (state["order_id"],))
        conn.execute("UPDATE tickets SET status = 'resolved' WHERE ticket_id = ?", (state["ticket_id"],))
        conn.execute(
            "INSERT INTO audit_log (thread_id, ticket_id, actor, action, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                thread_id,
                state["ticket_id"],
                decision.get("reviewer_id", "system"),
                "REFUND_ISSUED",
                json.dumps({"refund_id": refund_id, "amount": amount}),
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "execution_result": f"REFUND_ISSUED:{refund_id}:${amount:.2f}",
        "audit_events": [f"WRITE:REFUND_ISSUED:{refund_id}:${amount:.2f}"],
    }

def escalate_tier3_node(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    if runtime.context.actor_role == "readonly_viewer":
        raise PermissionError("Write blocked: readonly_viewer cannot escalate tickets.")

    conn = runtime.context.ops_conn
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    now = datetime.now(timezone.utc).isoformat()
    reason = state["deterministic_eval"].get("reason_code", "SLA_OR_CAP_ESCALATION")

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE tickets SET status = 'escalated', assigned_queue = 'tier3_specialist' WHERE ticket_id = ?",
            (state["ticket_id"],),
        )
        conn.execute(
            "INSERT INTO audit_log (thread_id, ticket_id, actor, action, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (thread_id, state["ticket_id"], "deterministic_engine", "ESCALATED_TIER3", json.dumps({"reason": reason}), now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "execution_result": f"ESCALATED_TIER3:{reason}",
        "audit_events": [f"WRITE:ESCALATED_TIER3:{reason}"],
    }

def finalize_rejection_node(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    conn = runtime.context.ops_conn
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    now = datetime.now(timezone.utc).isoformat()
    reason = (
        state["approval_decision"]["reviewer_note"]
        if state.get("approval_decision")
        else state["deterministic_eval"]["reason_code"]
    )
    conn.execute(
        "UPDATE tickets SET status = 'resolved' WHERE ticket_id = ?",
        (state["ticket_id"],),
    )
    conn.execute(
        "INSERT INTO audit_log (thread_id, ticket_id, actor, action, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (thread_id, state["ticket_id"], "system", "REFUND_REJECTED", json.dumps({"reason": reason}), now),
    )
    conn.commit()
    return {
        "execution_result": f"REJECTED:{reason}",
        "audit_events": [f"FINAL:REJECTED:{reason}"],
    }

def finalize_info_node(state: dict) -> dict:
    return {
        "execution_result": "INFO_RESPONSE_READY",
        "audit_events": ["FINAL:INFO_RESPONSE_READY"],
    }