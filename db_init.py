import os
import sqlite3

def init_ops_db(db_path: str = "data/support_ops.db") -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            tier TEXT CHECK(tier IN ('standard', 'pro', 'enterprise')) NOT NULL,
            lifetime_refund_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES customers(customer_id),
            product_name TEXT NOT NULL,
            category TEXT CHECK(category IN ('hardware', 'saas_subscription', 'digital_addon')) NOT NULL,
            amount_usd REAL NOT NULL,
            purchase_date TEXT NOT NULL,
            status TEXT CHECK(status IN ('delivered', 'in_transit', 'cancelled', 'refunded')) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES customers(customer_id),
            order_id TEXT REFERENCES orders(order_id),
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT CHECK(priority IN ('P1', 'P2', 'P3')) NOT NULL,
            status TEXT CHECK(status IN ('open', 'pending_approval', 'escalated', 'resolved')) NOT NULL,
            created_at TEXT NOT NULL,
            first_response_at TEXT,
            assigned_queue TEXT DEFAULT 'tier2_triage'
        );
        CREATE TABLE IF NOT EXISTS refund_ledger (
            refund_id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
            order_id TEXT NOT NULL REFERENCES orders(order_id),
            amount_usd REAL NOT NULL,
            decision TEXT CHECK(decision IN ('auto_approved', 'hitl_approved', 'rejected')) NOT NULL,
            approved_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn