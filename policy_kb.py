from dataclasses import dataclass

@dataclass
class PolicyDoc:
    page_content: str
    metadata: dict

DEMO_POLICIES = [
    PolicyDoc(
        page_content=(
            "REFUND POLICY (POL-REF-01): Hardware products are eligible for refund within 30 calendar days "
            "of purchase if defective or unsatisfactory. SaaS subscriptions have a 14-day refund window. "
            "Digital add-ons have a strict 7-day refund window. Orders already marked 'refunded' are ineligible."
        ),
        metadata={"doc_id": "POL-REF-01", "category": "refund"},
    ),
    PolicyDoc(
        page_content=(
            "APPROVAL AUTHORITY MATRIX (POL-AUTH-02): Tier-2 agents may auto-approve eligible refunds up to "
            "$50.00 USD ONLY if the customer has fewer than 3 lifetime refunds. Refunds between $50.01 and "
            "$500.00 USD (or any refund for customers with 3+ prior refunds) require Tier-2 Supervisor HITL approval. "
            "Refunds exceeding $500.00 USD must be escalated to Tier-3 Finance."
        ),
        metadata={"doc_id": "POL-AUTH-02", "category": "authorization"},
    ),
    PolicyDoc(
        page_content=(
            "SLA & ESCALATION POLICY (POL-SLA-03): Enterprise P1 tickets require first response within 1 hour "
            "and resolution within 4 hours. Pro P1/P2 tickets require 4h first response / 24h resolution. "
            "Standard tickets require 24h first response / 72h resolution. Breached SLA tickets must escalate."
        ),
        metadata={"doc_id": "POL-SLA-03", "category": "sla"},
    ),
    PolicyDoc(
        page_content=(
            "HARDWARE TROUBLESHOOTING (POL-TECH-04): For USB-C Docking Hubs failing to charge, instruct the "
            "user to disconnect power for 60 seconds (power cycle) and test with an OEM 65W+ adapter before RMA."
        ),
        metadata={"doc_id": "POL-TECH-04", "category": "troubleshooting"},
    ),
]

class SupportPolicyRetriever:
    """
    Adapter wrapper:
    - If you pass your Project 1 LangChain retriever (`project1_retriever`), it delegates `.invoke(query)` to it.
    - Otherwise, it uses keyword scoring over DEMO_POLICIES so the agent works out-of-the-box.
    """
    def __init__(self, project1_retriever=None):
        self.project1_retriever = project1_retriever

    def invoke(self, query: str) -> list[PolicyDoc]:
        if self.project1_retriever is not None:
            return self.project1_retriever.invoke(query)

        q_tokens = set(query.lower().split())
        scored = []
        for doc in DEMO_POLICIES:
            doc_tokens = set(doc.page_content.lower().split())
            overlap = len(q_tokens.intersection(doc_tokens))
            scored.append((overlap, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored if score > 0] or DEMO_POLICIES[:2]