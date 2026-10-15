from sqlalchemy import text
from support_tools import engine, get_order_status, get_delivery_info


def pick(status):
    with engine.connect() as c:
        return c.execute(text(
            "SELECT order_id FROM orders WHERE order_status = :s LIMIT 1"), {"s": status}).scalar()


for status in ("delivered", "shipped", "canceled"):
    oid = pick(status)
    print("\n==", status, oid)
    print(get_order_status.invoke({"order_id": oid}))
    print(get_delivery_info.invoke({"order_id": oid}))

print("\n== bad id")
print(get_order_status.invoke({"order_id": "does-not-exist"}))


