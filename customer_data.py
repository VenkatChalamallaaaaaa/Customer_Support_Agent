import streamlit as st
from sqlalchemy import bindparam, text
from support_tools import engine

# Orders from your earlier tests, so the demo covers: late + big refund,
# late + big refund, and a small auto-approved return.
DEMO_ORDERS = [
    "7797e37c568b84182c813b9b2492b384",
    "49d82571c200aac8b226cae094dc8f0c",
    "0c6b011f8a4f87010c23995f5807d152",
]


@st.cache_data(ttl=600)
def demo_customers():
    """[(customer_unique_id, label)] for the demo sign-in dropdown."""
    q = text("""
        SELECT DISTINCT c.customer_unique_id, c.customer_city, c.customer_state
        FROM orders o JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.order_id IN :ids
        ORDER BY c.customer_unique_id
    """).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        rows = conn.execute(q, {"ids": DEMO_ORDERS}).all()
    return [(r[0], f"Demo customer {i} · {r[1].title()}, {r[2]}")
            for i, r in enumerate(rows, start=1)]


@st.cache_data(ttl=60)
def list_orders(customer_unique_id):
    """All orders of one customer, newest first, with a short item summary."""
    q = text("""
        SELECT o.order_id, o.order_status, o.order_purchase_timestamp,
               (SELECT COALESCE(SUM(i.price + i.freight_value), 0)
                  FROM order_items i WHERE i.order_id = o.order_id) AS total,
               (SELECT string_agg(DISTINCT COALESCE(t.product_category_name_english,
                                                    p.product_category_name, 'item'), ', ')
                  FROM order_items i
                  JOIN products p ON p.product_id = i.product_id
                  LEFT JOIN product_category_name_translation t
                         ON t.product_category_name = p.product_category_name
                 WHERE i.order_id = o.order_id) AS items
        FROM orders o JOIN customers c ON c.customer_id = o.customer_id
        WHERE c.customer_unique_id = :cid
        ORDER BY o.order_purchase_timestamp DESC
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(q, {"cid": customer_unique_id}).mappings()]