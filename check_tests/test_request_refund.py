from sqlalchemy import text
from support_tools import engine, request_refund

with engine.connect() as c:
    small_order = c.execute(text("""
        SELECT o.order_id FROM orders o
        WHERE o.order_status = 'delivered'
          AND o.order_delivered_customer_date BETWEEN '2018-08-25' AND '2018-09-10'
          AND (SELECT SUM(price) FROM order_items WHERE order_id = o.order_id) BETWEEN 10 AND 90
          AND NOT EXISTS (SELECT 1 FROM order_payments
                          WHERE order_id = o.order_id AND payment_type = 'boleto')
        LIMIT 1""")).scalar()

tests = [
    ("small order, return -> auto approved", small_order, "return"),
    ("same order again -> duplicate refused", small_order, "return"),
    ("over R$100 damaged -> pending approval", "7797e37c568b84182c813b9b2492b384", "damaged_or_wrong_item"),
    ("old order -> not eligible", "e481f51cbdc54678b7cc49136f2d6af7", "return"),
]
for label, oid, reason in tests:
    print("\n==", label)
    print(request_refund.invoke({"order_id": oid, "reason": reason}))

with engine.connect() as c:
    print("\nrefunds table:")
    for row in c.execute(text("SELECT refund_id, order_id, amount, reason, status, decided_by FROM refunds ORDER BY refund_id")):
        print(tuple(row))