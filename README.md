# Autonomous Tier-2 Customer Support & Escalation Triage Agent

An enterprise-grade Agentic AI system built with **LangGraph 1.2** and **Gemini 3.8 Flash** that investigates Tier-2 customer support tickets, retrieves internal policies via a modular RAG adapter, enforces deterministic refund and SLA rules, and pauses behind a **Human-in-the-Loop (HITL)** approval gate before executing state-mutating database writes.

---

## Business Problem & Solution
Tier-1 chatbots fail on multi-step support escalations—such as damaged deliveries, duplicate refund attempts, SLA breaches, and policy exceptions—because resolving them requires cross-referencing customer history, company policies, and strict financial caps.

This system separates **probabilistic LLM reasoning** from **deterministic business logic and privileged writes**:
1. **Investigate (Read-Only):** Gemini 3.8 Flash inspects the ticket, queries customer/order records in SQLite, and retrieves relevant policy clauses via RAG.
2. **Propose (Structured Output):** The LLM emits a typed `TriageProposal` constrained by Pydantic JSON Schema.
3. **Evaluate (Deterministic Python):** Pure Python engines calculate exact return windows, dollar caps, lifetime refund limits, and SLA timers—overriding any prompt-injected instructions.
4. **Authorize (LangGraph HITL):** Refunds above $50 (or for customers with 3+ prior refunds) pause execution at `interrupt()` with `SqliteSaver` checkpointing until a human supervisor approves, modifies, or rejects the action.
5. **Execute & Audit (Atomic Writes):** Approved writes execute inside an idempotent `BEGIN IMMEDIATE` SQLite transaction and append an immutable entry to `audit_log`.

---

## Architecture & Execution Flow

```text
[START]
   │
   ▼
[intake] ──► Loads ticket, customer & order snapshot from support_ops.db
   │
   ▼
[investigator] ◄──────┐ (ReAct Loop: Read-Only Tools Only)
   │                  │
   ├─► tool_calls? ──► [readonly_tools] (lookup_policy_rag, get_ticket_and_order_snapshot)
   │
   ▼ (No more tool calls)
[synthesize_proposal] ──► Structured TriageProposal (Pydantic JSON Schema)
   │
   ▼
[deterministic_policy] ──► Pure Python Refund & SLA Rule Engines
   │
   ├──► auto_escalate / >$500 ──► [escalate_tier3] ──────────► [END]
   ├──► require_hitl ───────────► [human_approval] (interrupt)
   │                                  ├─► approve / modify ──► [execute_write] ──► [END]
   │                                  └─► reject ────────────► [finalize_rejection] ──► [END]
   ├──► auto_approve (<= $50) ──► [execute_write] ───────────► [END]
   ├──► reject (expired/dup) ───► [finalize_rejection] ──────► [END]
   └──► no_refund ──────────────► [finalize_info] ───────────► [END]
