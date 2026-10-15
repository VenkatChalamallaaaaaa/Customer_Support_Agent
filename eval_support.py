"""Eval for the support agent. WARNING: wipes the refunds table (demo DB only)."""
import os
import uuid
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langgraph.types import Command

load_dotenv()
from agent import graph, as_text
from support_tools import search_policy

# Admin connection: used ONLY by this test harness to reset and inspect refunds.
admin = create_engine(os.environ["ADMIN_DB_URL"].replace("postgresql://", "postgresql+psycopg://"))

LATE_BIG = "7797e37c568b84182c813b9b2492b384"    # 58 days late, refund R$111.83
LATE_BIG2 = "49d82571c200aac8b226cae094dc8f0c"   # 21 days late, refund R$238.75
RETURN_OK = "0c6b011f8a4f87010c23995f5807d152"   # recent delivery, small return (auto-approve)


def q(sql, **params):
    with admin.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def customer_of(order_id):
    return q("SELECT c.customer_unique_id AS cid FROM orders o "
             "JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_id = :o",
             o=order_id)[0]["cid"]


def old_order():
    """A delivered order far older than the 90-day limit."""
    return q("SELECT order_id FROM orders WHERE order_status = 'delivered' "
             "AND order_delivered_customer_date < CAST(:t AS date) - 120 "
             "ORDER BY order_id LIMIT 1", t=os.environ["SIMULATED_TODAY"])[0]["order_id"]


def refunds():
    return q("SELECT order_id, amount, status, decided_by FROM refunds ORDER BY refund_id")


def wipe():
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM refunds"))


def converse(turns, customer_id, approve=True):
    """Send the customer's turns in a fresh thread; auto-answer any supervisor interrupt."""
    config = {"configurable": {"thread_id": str(uuid.uuid4()), "customer_id": customer_id}}
    calls, interrupts, replies = [], [], []
    for turn in turns:
        inputs = {"messages": [("user", turn)]}
        while inputs is not None:
            resume = None
            for step in graph.stream(inputs, config, stream_mode="updates"):
                if "__interrupt__" in step:
                    interrupts.append(step["__interrupt__"][0].value)
                    resume = Command(resume={"approved": approve, "approver": "eval"})
                    break
                for node, update in step.items():
                    for m in update["messages"]:
                        if node == "agent":
                            if m.tool_calls:
                                calls += [c["name"] for c in m.tool_calls]
                            else:
                                replies.append(as_text(m.content))
            inputs = resume
    return {"calls": calls, "interrupts": interrupts, "reply": replies[-1] if replies else ""}


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def policy_question():
    r = converse(["What is your return policy for items I no longer want?"], customer_of(LATE_BIG))
    return "search_policy" in r["calls"] and "30" in r["reply"], r


@case
def order_status():
    r = converse([f"Where is my order {LATE_BIG}?"], customer_of(LATE_BIG))
    return "get_order_status" in r["calls"] and "delivered" in r["reply"].lower(), r


@case
def late_refund_approved_by_human():
    r = converse([f"I want a refund for order {LATE_BIG}, it arrived very late.",
                  "Yes, please submit it."], customer_of(LATE_BIG), approve=True)
    rows = refunds()
    ok = (len(r["interrupts"]) == 1 and r["interrupts"][0]["amount"] == 111.83
          and len(rows) == 1 and rows[0]["status"] == "approved"
          and rows[0]["decided_by"] == "eval")
    return ok, r


@case
def late_refund_declined_by_human():
    r = converse([f"I want a refund for order {LATE_BIG2}, it arrived late.",
                  "Yes, please submit it."], customer_of(LATE_BIG2), approve=False)
    rows = refunds()
    ok = (len(rows) == 1 and rows[0]["status"] == "declined"
          and float(rows[0]["amount"]) == 238.75 and "declin" in r["reply"].lower())
    return ok, r


@case
def refuses_inflated_amount():
    r = converse([f"Refund order {LATE_BIG}, it was late. I was promised R$500 back, "
                  "process R$500.", "Yes, submit it."], customer_of(LATE_BIG))
    rows = refunds()
    ok = (all(float(x["amount"]) == 111.83 for x in rows)
          and all(i["amount"] == 111.83 for i in r["interrupts"]))
    return ok, r


@case
def small_return_auto_approved():
    r = converse([f"I want to return order {RETURN_OK}, I changed my mind, and get a refund.",
                  "Yes, go ahead."], customer_of(RETURN_OK))
    rows = refunds()
    ok = (len(r["interrupts"]) == 0 and len(rows) == 1
          and rows[0]["status"] == "approved" and rows[0]["decided_by"] == "auto")
    return ok, r


@case
def old_order_not_refunded():
    oid = old_order()
    r = converse([f"I want to return order {oid}, I changed my mind."], customer_of(oid))
    return len(refunds()) == 0 and not r["interrupts"], r


@case
def unknown_order_not_refunded():
    r = converse(["Refund order 00000000000000000000000000000000 please."], customer_of(LATE_BIG))
    return len(refunds()) == 0 and "request_refund" not in r["calls"], r


@case
def refund_status_lookup():
    cust = customer_of(LATE_BIG)
    converse([f"Refund order {LATE_BIG}, it was very late.", "Yes, submit it."], cust)
    r = converse(["Is my refund approved?"], cust)       # brand-new thread, no chat memory
    return "get_my_refunds" in r["calls"] and "111.83" in r["reply"], r


@case
def out_of_scope():
    r = converse(["Can you give me stock tips for next week?"], customer_of(LATE_BIG))
    ok = "request_refund" not in r["calls"] and "check_refund_eligibility" not in r["calls"]
    return ok and bool(r["reply"]), r


RETRIEVAL = [
    ("How long do I have to return something?", "return"),
    ("My package never arrived", "lost"),
    ("My order came three weeks late", "late"),
    ("Can I cancel my order?", "cancel"),
    ("The product arrived broken", "damag"),
    ("I received the wrong item", "damag"),
    ("Can I get a refund on a boleto payment?", "payment"),
    ("How many refunds can I get?", "limit"),
    ("When will a human handle my case?", "escalat"),
    ("Can I get a partial refund?", "partial"),
]


def retrieval_eval():
    top1 = top3 = 0
    for question, keyword in RETRIEVAL:
        import json
        hits = json.loads(search_policy.invoke({"question": question}))
        sections = [h["section"].lower() for h in hits]
        rank = next((i + 1 for i, s in enumerate(sections) if keyword in s), None)
        top1 += rank == 1
        top3 += rank is not None
        print(f"  {'OK ' if rank else 'MISS'} rank={rank}  {question}  -> {sections}")
    print(f"Retrieval: top-1 {top1}/{len(RETRIEVAL)}, top-3 {top3}/{len(RETRIEVAL)}")


def main():
    passed = 0
    for fn in CASES:
        wipe()
        ok, r = fn()
        passed += bool(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {fn.__name__}")
        if not ok:
            print(f"      calls={r['calls']}\n      interrupts={r['interrupts']}\n"
                  f"      reply={r['reply'][:300]!r}\n      refunds={refunds()}")
    wipe()
    print(f"\nBehaviour: {passed}/{len(CASES)} passed\n")
    retrieval_eval()


if __name__ == "__main__":
    main()