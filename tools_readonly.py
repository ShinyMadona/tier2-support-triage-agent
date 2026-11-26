from langchain.tools import tool, ToolRuntime

@tool
def lookup_policy_rag(query: str, runtime: ToolRuntime) -> str:
    """Search existing company support policy RAG knowledge base (READ-ONLY)."""
    retriever = runtime.context.rag_retriever
    docs = retriever.invoke(query)
    if not docs:
        return "NO_POLICY_MATCH"
    return "\n---\n".join(
        f"[{d.metadata.get('doc_id', 'policy')}] {d.page_content}" for d in docs[:4]
    )

@tool
def get_ticket_and_order_snapshot(runtime: ToolRuntime) -> dict:
    """Fetch authoritative customer, order, and ticket facts from SQLite (READ-ONLY)."""
    conn = runtime.context.ops_conn
    ticket_id = runtime.state["ticket_id"]
    row = conn.execute(
        """
        SELECT t.*, c.name AS customer_name, c.tier, c.lifetime_refund_count,
               o.product_name, o.category, o.amount_usd, o.purchase_date, o.status AS order_status
        FROM tickets t
        JOIN customers c ON t.customer_id = c.customer_id
        LEFT JOIN orders o ON t.order_id = o.order_id
        WHERE t.ticket_id = ?
        """,
        (ticket_id,),
    ).fetchone()
    return dict(row) if row else {"error": f"Ticket {ticket_id} not found"}

READONLY_TOOLS = [lookup_policy_rag, get_ticket_and_order_snapshot]