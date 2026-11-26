from datetime import datetime, timedelta, timezone
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from db_init import init_ops_db
from deterministic_engines import evaluate_refund_policy, evaluate_sla_status
from graph_builder import build_triage_graph
from graph_state import AgentContext, TriageProposal
from seed_data import seed_demo_data

class MockProposalLLM:
    """Deterministic stub LLM so offline tests verify graph routing, HITL, and security guards without spending tokens."""
    def __init__(self, proposal: TriageProposal):
        self._proposal = proposal

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, schema, method="json_schema"):
        return self

    def invoke(self, messages):
        if isinstance(messages[0].content, str) and "Produce the final structured" in messages[0].content:
            return self._proposal
        return AIMessage(content="Investigation complete.")

def test_deterministic_refund_rules():
    now = datetime.now(timezone.utc)
    # 1. Auto-approve under $50
    res = evaluate_refund_policy(
        {"status": "delivered", "amount_usd": 30.0, "category": "hardware", "purchase_date": (now - timedelta(days=5)).isoformat(), "lifetime_refund_count": 0},
        28.0,
        now,
    )
    assert res["route"] == "auto_approve"

    # 2. HITL required over $50
    res_hitl = evaluate_refund_policy(
        {"status": "delivered", "amount_usd": 140.0, "category": "hardware", "purchase_date": (now - timedelta(days=5)).isoformat(), "lifetime_refund_count": 0},
        140.0,
        now,
    )
    assert res_hitl["route"] == "require_hitl"

    # 3. Expired digital addon (>7 days)
    res_exp = evaluate_refund_policy(
        {"status": "delivered", "amount_usd": 35.0, "category": "digital_addon", "purchase_date": (now - timedelta(days=10)).isoformat(), "lifetime_refund_count": 0},
        35.0,
        now,
    )
    assert res_exp["route"] == "reject"

def test_deterministic_sla_breach():
    now = datetime.now(timezone.utc)
    sla = evaluate_sla_status(
        {"tier": "enterprise", "priority": "P1", "created_at": (now - timedelta(hours=4.5)).isoformat(), "first_response_at": None},
        now,
    )
    assert sla["sla_status"] == "breached"
    assert sla["auto_escalate"] is True

def test_hitl_interrupt_and_resume_flow(tmp_path):
    db_file = str(tmp_path / "test_ops.db")
    seed_demo_data(db_file)
    conn = init_ops_db(db_file)

    mock_prop = TriageProposal(
        intent="refund_request",
        proposed_action="issue_refund",
        requested_refund_usd=140.0,
        rationale="Headphones arrived cracked within 30-day window.",
        policy_citations=["POL-REF-01", "POL-AUTH-02"],
        customer_reply_draft="Your $140 refund is pending supervisor approval.",
    )
    graph = build_triage_graph(checkpointer=MemorySaver(), llm_override=MockProposalLLM(mock_prop))
    config = {"configurable": {"thread_id": "test-hitl-1"}}
    ctx = AgentContext(ops_conn=conn, rag_retriever=None, actor_role="tier2_agent")

    # Step 1: Graph pauses at interrupt()
    graph.invoke({"ticket_id": "TKT-1002", "messages": []}, config=config, context=ctx)
    snap = graph.get_state(config)
    assert snap.next == ("human_approval",)

    # Step 2: Supervisor approves modified amount ($70)
    out = graph.invoke(
        Command(resume={"action": "modify_amount", "approved_amount_usd": 70.0, "reviewer_note": "Partial refund approved"}),
        config=config,
        context=ctx,
    )
    assert "REFUND_ISSUED" in out["execution_result"]
    assert "$70.00" in out["execution_result"]

def test_readonly_viewer_blocked_from_writes(tmp_path):
    db_file = str(tmp_path / "test_sec.db")
    seed_demo_data(db_file)
    conn = init_ops_db(db_file)

    mock_prop = TriageProposal(
        intent="refund_request",
        proposed_action="issue_refund",
        requested_refund_usd=28.0,
        rationale="Defective USB-C hub.",
        policy_citations=["POL-REF-01"],
        customer_reply_draft="Refund approved.",
    )
    graph = build_triage_graph(checkpointer=MemorySaver(), llm_override=MockProposalLLM(mock_prop))
    config = {"configurable": {"thread_id": "test-sec-1"}}
    ctx = AgentContext(ops_conn=conn, rag_retriever=None, actor_role="readonly_viewer")

    with pytest.raises(PermissionError):
        graph.invoke({"ticket_id": "TKT-1001", "messages": []}, config=config, context=ctx)