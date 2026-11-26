import sqlite3
import uuid
import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from db_init import init_ops_db
from graph_builder import build_triage_graph
from graph_state import AgentContext
from policy_kb import SupportPolicyRetriever

load_dotenv()
st.set_page_config(page_title="Tier-2 Support Triage Agent", layout="wide")

@st.cache_resource
def get_runtime_bundle():
    ops_conn = init_ops_db("data/support_ops.db")
    ckpt_conn = sqlite3.connect("data/langgraph_checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(ckpt_conn)
    graph = build_triage_graph(checkpointer=checkpointer)
    retriever = SupportPolicyRetriever(project1_retriever=None)  # Plug Project 1 retriever here
    return graph, ops_conn, retriever

graph, ops_conn, retriever = get_runtime_bundle()

st.title("Autonomous Tier-2 Support & Escalation Triage Agent")

tickets = ops_conn.execute("SELECT ticket_id, subject, priority, status FROM tickets").fetchall()
ticket_options = {f"{r['ticket_id']} [{r['priority']}] ({r['status']}) - {r['subject']}": r["ticket_id"] for r in tickets}

col1, col2 = st.columns([2, 1])
with col1:
    selected_label = st.selectbox("Select Incoming Ticket", list(ticket_options.keys()))
    selected_ticket_id = ticket_options[selected_label]
with col2:
    actor_role = st.selectbox("Session Role (Security Boundary Test)", ["tier2_agent", "readonly_viewer"])

if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None

if st.button("Run Agent Triage", type="primary"):
    st.session_state.active_thread_id = f"{selected_ticket_id}-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": st.session_state.active_thread_id}}
    context = AgentContext(ops_conn=ops_conn, rag_retriever=retriever, actor_role=actor_role)
    graph.invoke({"ticket_id": selected_ticket_id, "messages": []}, config=config, context=context)
    st.rerun()

if st.session_state.active_thread_id:
    config = {"configurable": {"thread_id": st.session_state.active_thread_id}}
    context = AgentContext(ops_conn=ops_conn, rag_retriever=retriever, actor_role=actor_role)
    snapshot = graph.get_state(config)
    values = snapshot.values

    pending_interrupts = [intr for task in snapshot.tasks for intr in getattr(task, "interrupts", ())]

    if snapshot.next and pending_interrupts:
        payload = pending_interrupts[0].value
        st.warning(f"HUMAN APPROVAL REQUIRED — Ticket {payload['ticket_id']} ({payload['reason_code']})")
        st.json(payload)

        with st.form("hitl_form"):
            decision = st.radio("Supervisor Decision", ["approve", "modify_amount", "reject"])
            adj_amount = st.number_input(
                "Approved Refund Amount (USD)",
                min_value=0.0,
                max_value=float(payload["max_refundable_usd"]),
                value=float(payload["requested_refund_usd"]),
            )
            note = st.text_input("Mandatory Reviewer Note", value="Verified policy eligibility and evidence.")
            if st.form_submit_button("Submit Decision"):
                graph.invoke(
                    Command(resume={"action": decision, "approved_amount_usd": adj_amount, "reviewer_note": note}),
                    config=config,
                    context=context,
                )
                st.rerun()

    if values:
        st.subheader("Investigation & Execution Trace")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**LLM Structured Proposal**")
            st.json(values.get("proposal", {}))
        with c2:
            st.markdown("**Deterministic Rule Engine Output**")
            st.json(values.get("deterministic_eval", {}))

        st.markdown("**Audit Trail Events**")
        for ev in values.get("audit_events", []):
            st.code(ev)

        if values.get("execution_result"):
            st.success(f"Final Outcome: {values['execution_result']}")