from sqlalchemy import text
from support_tools import engine, check_refund_eligibility


def pick(sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


CASES = [
    ("recent delivery, return",
     "SELECT order_id FROM orders WHERE order_status='delivered' "
     "AND order_delivered_customer_date BETWEEN '2018-08-25' AND '2018-09-10' LIMIT 1", "return"),
    ("delivered days ago, damaged",
     "SELECT order_id FROM orders WHERE order_status='delivered' "
     "AND order_delivered_customer_date BETWEEN '2018-09-11' AND '2018-09-14' LIMIT 1", "damaged_or_wrong_item"),
    ("old delivery, return (should decline)",
     "SELECT order_id FROM orders WHERE order_status='delivered' "
     "AND order_delivered_customer_date < '2017-12-01' LIMIT 1", "return"),
    ("shipped long ago, not received (lost)",
     "SELECT order_id FROM orders WHERE order_status='shipped' "
     "AND order_estimated_delivery_date < '2018-08-01' LIMIT 1", "not_received"),
    ("very late delivery",
     "SELECT order_id FROM orders WHERE order_status='delivered' "
     "AND order_delivered_customer_date > order_estimated_delivery_date + interval '16 days' "
     "AND order_delivered_customer_date BETWEEN '2018-06-25' AND '2018-09-14' LIMIT 1", "late_delivery"),
    ("canceled order",
     "SELECT order_id FROM orders WHERE order_status='canceled' LIMIT 1", "not_received"),
]

for label, sql, reason in CASES:
    oid = pick(sql)
    print("\n==", label, "|", reason)
    if oid is None:
        print("no matching order in the data")
        continue
    print(check_refund_eligibility.invoke({"order_id": oid, "reason": reason}))