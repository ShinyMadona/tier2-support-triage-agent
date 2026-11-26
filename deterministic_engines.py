from datetime import datetime, timezone

REFUND_WINDOWS_DAYS = {
    "hardware": 30,
    "saas_subscription": 14,
    "digital_addon": 7,
}

SLA_TARGETS_HOURS = {
    ("enterprise", "P1"): (1.0, 4.0),
    ("enterprise", "P2"): (2.0, 8.0),
    ("enterprise", "P3"): (8.0, 24.0),
    ("pro", "P1"): (4.0, 24.0),
    ("pro", "P2"): (4.0, 24.0),
    ("pro", "P3"): (12.0, 48.0),
    ("standard", "P1"): (8.0, 24.0),
    ("standard", "P2"): (12.0, 48.0),
    ("standard", "P3"): (24.0, 72.0),
}

def evaluate_refund_policy(
    order_row: dict | None,
    requested_refund_usd: float,
    now_utc: datetime | None = None,
) -> dict:
    now = now_utc or datetime.now(timezone.utc)

    if requested_refund_usd <= 0 or not order_row:
        return {
            "eligible": False,
            "route": "no_refund",
            "reason_code": "NO_REFUND_REQUESTED_OR_MISSING_ORDER",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": 0.0,
        }

    order_status = order_row["status"]
    amount_usd = float(order_row["amount_usd"])
    category = order_row["category"]
    prior_refunds = int(order_row["lifetime_refund_count"])
    purchase_dt = datetime.fromisoformat(order_row["purchase_date"])
    if purchase_dt.tzinfo is None:
        purchase_dt = purchase_dt.replace(tzinfo=timezone.utc)

    days_since_purchase = (now - purchase_dt).total_seconds() / 86400.0
    max_window = REFUND_WINDOWS_DAYS.get(category, 14)

    if order_status == "refunded":
        return {
            "eligible": False,
            "route": "reject",
            "reason_code": "ALREADY_REFUNDED",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": 0.0,
        }

    if requested_refund_usd > amount_usd:
        return {
            "eligible": False,
            "route": "reject",
            "reason_code": "EXCEEDS_ORDER_AMOUNT",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": amount_usd,
        }

    if days_since_purchase > max_window:
        return {
            "eligible": False,
            "route": "reject",
            "reason_code": f"OUTSIDE_{max_window}_DAY_WINDOW",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": 0.0,
        }

    if requested_refund_usd > 500.0:
        return {
            "eligible": True,
            "route": "tier3_finance",
            "reason_code": "EXCEEDS_TIER2_500_CAP",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": amount_usd,
        }

    if requested_refund_usd <= 50.0 and prior_refunds < 3:
        return {
            "eligible": True,
            "route": "auto_approve",
            "reason_code": "ELIGIBLE_AUTO_APPROVE",
            "requested_refund_usd": requested_refund_usd,
            "max_refundable_usd": amount_usd,
        }

    return {
        "eligible": True,
        "route": "require_hitl",
        "reason_code": "REQUIRES_SUPERVISOR_HITL",
        "requested_refund_usd": requested_refund_usd,
        "max_refundable_usd": amount_usd,
    }

def evaluate_sla_status(
    ticket_row: dict,
    now_utc: datetime | None = None,
) -> dict:
    now = now_utc or datetime.now(timezone.utc)
    tier = ticket_row.get("tier", "standard")
    priority = ticket_row.get("priority", "P3")
    created_dt = datetime.fromisoformat(ticket_row["created_at"])
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)

    first_resp_target, resolution_target = SLA_TARGETS_HOURS.get((tier, priority), (24.0, 72.0))
    elapsed_hours = (now - created_dt).total_seconds() / 3600.0
    unanswered = ticket_row.get("first_response_at") is None

    active_target = first_resp_target if unanswered else resolution_target
    ratio = elapsed_hours / active_target

    if ratio >= 1.0:
        status = "breached"
        auto_escalate = True
    elif ratio >= 0.75:
        status = "at_risk"
        auto_escalate = False
    else:
        status = "ok"
        auto_escalate = False

    return {
        "sla_status": status,
        "elapsed_hours": round(elapsed_hours, 2),
        "target_hours": active_target,
        "auto_escalate": auto_escalate,
    }