import os, json
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langchain_core.tools import tool
from langgraph.types import interrupt
from langchain_core.runnables import RunnableConfig

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
SIMULATED_TODAY = datetime.fromisoformat(os.getenv("SIMULATED_TODAY", "2018-09-15"))


def _fetch_order(order_id: str):
    sql = text("""
        SELECT o.order_id, o.order_status, c.customer_unique_id, c.customer_state,
               o.order_purchase_timestamp, o.order_delivered_customer_date,
               o.order_estimated_delivery_date
        FROM orders o JOIN customers c USING (customer_id)
        WHERE o.order_id = :oid
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, {"oid": order_id}).mappings().first()
    return dict(row) if row else None


@tool
def get_order_status(order_id: str) -> str:
    """Look up an order by its order_id. Returns status, key dates, number of items,
    items total, freight total and payment methods. Use this first for any question
    about a specific order."""
    order = _fetch_order(order_id.strip())
    if not order:
        return json.dumps({"error": f"No order found with id {order_id}"})
    with engine.connect() as conn:
        items = conn.execute(text(
            "SELECT COUNT(*) AS item_count, COALESCE(SUM(price),0) AS items_total, "
            "COALESCE(SUM(freight_value),0) AS freight_total "
            "FROM order_items WHERE order_id = :oid"), {"oid": order["order_id"]}).mappings().first()
        pays = conn.execute(text(
            "SELECT payment_type, SUM(payment_value) AS amount "
            "FROM order_payments WHERE order_id = :oid GROUP BY payment_type"),
            {"oid": order["order_id"]}).mappings().all()
    result = {**order, **dict(items), "payments": [dict(p) for p in pays]}
    return json.dumps(result, default=str)


@tool
def get_delivery_info(order_id: str) -> str:
    """Return delivery details for an order: estimated date, delivered date, how many
    days late it was (positive = late), days since delivery, or days past the estimate
    if it has not been delivered. Use this for questions about late or lost orders."""
    order = _fetch_order(order_id.strip())
    if not order:
        return json.dumps({"error": f"No order found with id {order_id}"})
    est = order["order_estimated_delivery_date"]
    dlv = order["order_delivered_customer_date"]
    info = {
        "order_id": order["order_id"],
        "status": order["order_status"],
        "estimated_delivery_date": est,
        "delivered_date": dlv,
        "today": SIMULATED_TODAY,
    }
    if dlv:
        info["days_late"] = (dlv - est).days
        info["days_since_delivery"] = (SIMULATED_TODAY - dlv).days
    elif est:
        info["days_past_estimate"] = (SIMULATED_TODAY - est).days
    return json.dumps(info, default=str)


REFUND_AUTO_LIMIT = 100.0     # above this, a human must approve
RETURN_WINDOW_DAYS = 30
DAMAGE_REPORT_DAYS = 7
MAX_AGE_DAYS = 90
LATE_FULL_REFUND_DAYS = 15
LOST_AFTER_DAYS = 20
MAX_REFUNDS = 3
VALID_REASONS = {"return", "damaged_or_wrong_item", "late_delivery", "not_received"}


def _order_amounts(order_id: str):
    # Scalar subqueries: each total is computed on its own table, so nothing is multiplied.
    sql = text("""
        SELECT
          (SELECT COALESCE(SUM(price), 0) FROM order_items WHERE order_id = :oid) AS items_total,
          (SELECT COALESCE(SUM(freight_value), 0) FROM order_items WHERE order_id = :oid) AS freight_total,
          (SELECT COALESCE(SUM(payment_value), 0) FROM order_payments WHERE order_id = :oid) AS payment_total,
          (SELECT string_agg(DISTINCT payment_type, ',') FROM order_payments WHERE order_id = :oid) AS payment_types
    """)
    with engine.connect() as conn:
        row = conn.execute(sql, {"oid": order_id}).mappings().first()
    return {
        "items_total": float(row["items_total"]),
        "freight_total": float(row["freight_total"]),
        "payment_total": float(row["payment_total"]),
        "payment_types": (row["payment_types"] or "").split(","),
    }


def _approved_refund_count(customer_unique_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM refunds WHERE customer_unique_id = :c AND status = 'approved'"),
            {"c": customer_unique_id}).scalar()


@tool
def check_refund_eligibility(order_id: str, reason: str) -> str:
    """Check whether an order qualifies for a refund under the store policy.
    reason must be one of: 'return' (customer changed their mind), 'damaged_or_wrong_item',
    'late_delivery', 'not_received'. Returns whether it is eligible, the refund amount,
    whether a human must approve it, and the policy reasons. Always call this before
    request_refund, and never promise a refund before it says eligible."""
    reason = reason.strip().lower()
    if reason not in VALID_REASONS:
        return json.dumps({"error": f"reason must be one of {sorted(VALID_REASONS)}"})
    order = _fetch_order(order_id.strip())
    if not order:
        return json.dumps({"error": f"No order found with id {order_id}"})

    amts = _order_amounts(order["order_id"])
    items, freight, paid = amts["items_total"], amts["freight_total"], amts["payment_total"]
    status = order["order_status"]
    est = order["order_estimated_delivery_date"]
    dlv = order["order_delivered_customer_date"]
    amount, notes = 0.0, []

    if status == "canceled":
        notes.append("Order was canceled; any charge is refunded automatically within 7 business days.")
    elif status == "unavailable":
        amount = paid
        notes.append("Item was unavailable: full refund.")
    elif dlv is None:
        days_past = (SIMULATED_TODAY - est).days
        if reason == "not_received" and days_past >= LOST_AFTER_DAYS:
            amount = items + freight
            notes.append(f"Order is {days_past} days past its estimated date: treated as lost, full refund including shipping.")
        elif reason == "not_received":
            notes.append(f"Order is only {max(days_past, 0)} days past its estimated date; it is treated as lost after {LOST_AFTER_DAYS} days.")
        else:
            notes.append("Order has not been delivered yet; return, damage and late-delivery refunds apply after delivery.")
    else:
        days_since = (SIMULATED_TODAY - dlv).days
        days_late = (dlv - est).days
        if days_since < 0:
            notes.append("Order is not delivered yet as of today.")
        elif days_since > MAX_AGE_DAYS:
            notes.append(f"Delivered {days_since} days ago; refunds are declined after {MAX_AGE_DAYS} days.")
        elif reason == "damaged_or_wrong_item":
            if days_since <= DAMAGE_REPORT_DAYS:
                amount = items + freight
                notes.append("Damaged or wrong item reported within 7 days: full refund including shipping, no return needed.")
            else:
                notes.append(f"Delivered {days_since} days ago; damage must be reported within {DAMAGE_REPORT_DAYS} days.")
        elif reason == "return":
            if days_since <= RETURN_WINDOW_DAYS:
                amount = items
                notes.append("Within the 30-day return window: refund of the item price (shipping not refunded).")
            else:
                notes.append(f"Delivered {days_since} days ago; the return window is {RETURN_WINDOW_DAYS} days.")
        elif reason == "late_delivery":
            if days_late > LATE_FULL_REFUND_DAYS:
                amount = items + freight
                notes.append(f"Delivered {days_late} days late (more than {LATE_FULL_REFUND_DAYS}): full refund, no return needed.")
            elif days_late > 0:
                amount = freight
                notes.append(f"Delivered {days_late} days late: shipping fee refund.")
            else:
                notes.append("Order arrived on or before its estimated date.")
        elif reason == "not_received":
            notes.append(f"Order is recorded as delivered on {dlv}.")

    amount = round(min(amount, paid), 2) if paid else round(amount, 2)

    escalate = []
    if amount > 0:
        if amount > REFUND_AUTO_LIMIT:
            escalate.append(f"Amount above R${REFUND_AUTO_LIMIT:.0f}: human approval required.")
        if "boleto" in amts["payment_types"]:
            escalate.append("Paid by boleto: bank details needed, human agent required.")
        if _approved_refund_count(order["customer_unique_id"]) >= MAX_REFUNDS:
            escalate.append(f"Customer already has {MAX_REFUNDS} approved refunds: human review required.")

    return json.dumps({
        "order_id": order["order_id"],
        "reason": reason,
        "eligible": amount > 0,
        "refund_amount": amount,
        "needs_human_approval": bool(escalate),
        "policy_notes": notes + escalate,
    })

@tool
def request_refund(order_id: str, reason: str) -> str:
    """Record a refund request for an order. Call this only after check_refund_eligibility
    says the order is eligible and the customer has confirmed they want the refund.
    reason must be one of: 'return', 'damaged_or_wrong_item', 'late_delivery', 'not_received'.
    The amount and approval status are decided by the system, not by you."""
    decision = json.loads(check_refund_eligibility.invoke({"order_id": order_id, "reason": reason}))
    if "error" in decision:
        return json.dumps(decision)
    if not decision["eligible"]:
        return json.dumps({"recorded": False,
                           "message": "Not eligible for a refund.",
                           "policy_notes": decision["policy_notes"]})

    order = _fetch_order(decision["order_id"])
    status = "pending_approval" if decision["needs_human_approval"] else "approved"
    decided_by = None if decision["needs_human_approval"] else "auto"

    with engine.begin() as conn:   # begin() commits the insert when the block ends
        existing = conn.execute(text(
            "SELECT refund_id, status FROM refunds "
            "WHERE order_id = :oid AND status IN ('approved', 'pending_approval')"),
            {"oid": order["order_id"]}).first()
        if existing:
            return json.dumps({"recorded": False,
                               "message": f"A refund already exists for this order (id {existing[0]}, status {existing[1]})."})
        refund_id = conn.execute(text(
            "INSERT INTO refunds (order_id, customer_unique_id, amount, reason, status, decided_by) "
            "VALUES (:oid, :cust, :amt, :reason, :status, :by) RETURNING refund_id"),
            {"oid": order["order_id"], "cust": order["customer_unique_id"],
             "amt": decision["refund_amount"], "reason": decision["reason"],
             "status": status, "by": decided_by}).scalar()

    return json.dumps({
        "recorded": True,
        "refund_id": refund_id,
        "amount": decision["refund_amount"],
        "status": status,
        "message": ("Refund approved automatically." if status == "approved"
                    else "Refund recorded and waiting for human approval."),
        "policy_notes": decision["policy_notes"],
    })


_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


@tool
def search_policy(question: str) -> str:
    """Search the store's customer policy (returns, refunds, late or lost deliveries,
    cancellations, payment methods, escalation rules). Use this for general policy
    questions such as 'how long do I have to return something?'. Returns the three most
    relevant policy sections. Answer only from the returned text. For a decision about a
    specific order, use check_refund_eligibility instead."""
    emb = _get_embedder().encode(question, normalize_embeddings=True)
    qvec = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
    sql = text("""
        SELECT section, content, 1 - (embedding <=> CAST(:q AS vector)) AS similarity
        FROM policy_chunks
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"q": qvec, "k": 3}).mappings().all()
    return json.dumps([
        {"section": r["section"], "similarity": round(float(r["similarity"]), 2), "text": r["content"]}
        for r in rows
    ])

@tool
def request_refund(order_id: str, reason: str) -> str:
    """Record a refund request for an order. Call this only after check_refund_eligibility
    says the order is eligible and the customer has confirmed they want the refund.
    reason must be one of: 'return', 'damaged_or_wrong_item', 'late_delivery', 'not_received'.
    The amount and approval are decided by the system, not by you. Refunds that need review
    pause until a human reviewer decides."""
    decision = json.loads(check_refund_eligibility.invoke({"order_id": order_id, "reason": reason}))
    if "error" in decision:
        return json.dumps(decision)
    if not decision["eligible"]:
        return json.dumps({"recorded": False,
                           "message": "Not eligible for a refund.",
                           "policy_notes": decision["policy_notes"]})

    order = _fetch_order(decision["order_id"])

    # Read-only duplicate check. It sits BEFORE the interrupt, so repeating it on resume is harmless.
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT refund_id, status FROM refunds "
            "WHERE order_id = :oid AND status IN ('approved', 'pending_approval')"),
            {"oid": order["order_id"]}).first()
    if existing:
        return json.dumps({"recorded": False,
                           "message": f"A refund already exists for this order (id {existing[0]}, status {existing[1]})."})

    if decision["needs_human_approval"]:
        verdict = interrupt({
            "order_id": order["order_id"],
            "customer": order["customer_unique_id"],
            "amount": decision["refund_amount"],
            "reason": decision["reason"],
            "policy_notes": decision["policy_notes"],
        })
        status = "approved" if verdict.get("approved") else "declined"
        decided_by = verdict.get("approver", "human")
    else:
        status, decided_by = "approved", "auto"

    # The write happens only after any human decision, so it runs exactly once.
    with engine.begin() as conn:
        refund_id = conn.execute(text(
            "INSERT INTO refunds (order_id, customer_unique_id, amount, reason, status, decided_by) "
            "VALUES (:oid, :cust, :amt, :reason, :status, :by) RETURNING refund_id"),
            {"oid": order["order_id"], "cust": order["customer_unique_id"],
             "amt": decision["refund_amount"], "reason": decision["reason"],
             "status": status, "by": decided_by}).scalar()

    if status == "approved":
        msg = "Refund approved automatically." if decided_by == "auto" else "Refund approved by a human reviewer."
    else:
        msg = "Refund declined by a human reviewer."
    return json.dumps({"recorded": True, "refund_id": refund_id, "amount": decision["refund_amount"],
                       "status": status, "message": msg, "policy_notes": decision["policy_notes"]})


@tool
def get_my_refunds(config: RunnableConfig) -> str:
    """List the signed-in customer's refund requests and their status
    (approved, pending_approval or declined). Use this whenever the customer asks
    about a refund they already requested. It takes no arguments."""
    customer_id = (config.get("configurable") or {}).get("customer_id")
    if not customer_id:
        return json.dumps({"error": "No signed-in customer."})
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT refund_id, order_id, amount, reason, status, decided_by, created_at "
            "FROM refunds WHERE customer_unique_id = :c ORDER BY created_at DESC"),
            {"c": customer_id}).mappings().all()
    if not rows:
        return json.dumps({"refunds": [], "message": "No refund requests found."})
    return json.dumps({"refunds": [dict(r) for r in rows]}, default=str)