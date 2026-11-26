import operator
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

class TriageProposal(BaseModel):
    intent: Literal["refund_request", "sla_escalation", "technical_guidance", "account_change"]
    proposed_action: Literal["none", "issue_refund", "escalate_tier3", "resolve_ticket"]
    requested_refund_usd: float = Field(default=0.0, ge=0.0)
    rationale: str
    policy_citations: list[str] = Field(default_factory=list)
    customer_reply_draft: str

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    ticket_id: str
    customer_id: str
    order_id: str | None
    ticket_snapshot: dict[str, Any] | None
    proposal: dict[str, Any] | None
    deterministic_eval: dict[str, Any] | None
    approval_decision: dict[str, Any] | None
    execution_result: str | None
    audit_events: Annotated[list[str], operator.add]

@dataclass(frozen=True)
class AgentContext:
    ops_conn: Any
    rag_retriever: Any
    actor_role: str = "tier2_agent"