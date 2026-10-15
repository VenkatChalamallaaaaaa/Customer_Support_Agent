import uuid
import streamlit as st
from langgraph.types import Command
from agent import graph, as_text
import customer_data
import shared
import ui

st.set_page_config(page_title="Marketly Support", page_icon="🛍️",
                   layout="centered", initial_sidebar_state="collapsed")
ui.apply_theme("#4f46e5")
ui.navbar("Marketly", "Help Center")

SUGGESTIONS = ["What is your return policy?", "What if my package never arrives?",
               "How do refunds work for late orders?"]


def new_session():
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []
    st.session_state.tool_log = []
    st.session_state.pending = None


if "customer" not in st.session_state:
    st.session_state.customer = None
if "thread_id" not in st.session_state:
    new_session()

# ---------- demo sign-in ----------
if st.session_state.customer is None:
    st.markdown('<div class="hero"><h1>Welcome to Marketly</h1>'
                '<p>Sign in to see your orders and get help.</p></div>',
                unsafe_allow_html=True)
    options = customer_data.demo_customers()
    labels = [label for _, label in options]
    choice = st.selectbox("Demo sign-in: pick a customer", labels)
    if st.button("Sign in", type="primary", use_container_width=True):
        cid, label = options[labels.index(choice)]
        st.session_state.customer = {"id": cid, "label": label}
        st.rerun()
    st.stop()

customer = st.session_state.customer
config = {"configurable": {"thread_id": st.session_state.thread_id,
                           "customer_id": customer["id"]}}

left, mid, right = st.columns([3, 1, 1])
left.markdown(f"👤 Signed in as **{customer['label']}**")
if mid.button("🏠 Home", disabled=not st.session_state.history, use_container_width=True):
    shared.cancel(st.session_state.thread_id)   # drop any approval still waiting
    new_session()                               # fresh thread, empty chat
    st.rerun()
if right.button("Sign out", use_container_width=True):
    shared.cancel(st.session_state.thread_id)
    st.session_state.customer = None
    new_session()
    st.rerun()


def run(inputs):
    for step in graph.stream(inputs, config, stream_mode="updates"):
        if "__interrupt__" in step:
            payload = step["__interrupt__"][0].value
            st.session_state.pending = payload
            shared.submit(st.session_state.thread_id, payload)
            return
        for node, update in step.items():
            for m in update["messages"]:
                if node == "agent":
                    if m.tool_calls:
                        for c in m.tool_calls:
                            st.session_state.tool_log.append(f"call: {c['name']} {c['args']}")
                    else:
                        st.session_state.history.append({
                            "role": "assistant", "content": as_text(m.content),
                            "tools": st.session_state.tool_log})
                        st.session_state.tool_log = []
                elif node == "tools":
                    st.session_state.tool_log.append(f"result: {m.content[:300]}")


@st.fragment(run_every=2)
def waiting_for_supervisor():
    decision = shared.take_decision(st.session_state.thread_id)
    if decision is None:
        st.info("⏳ Your refund request is with a supervisor for review. "
                "This page updates automatically.")
        return
    st.session_state.pending = None
    with st.spinner("Supervisor has decided. Updating..."):
        run(Command(resume=decision))
    st.rerun()


# ---------- your orders ----------
def order_card(o):
    ref = "#" + o["order_id"][:8].upper()
    items = (o["items"] or "order").replace("_", " ").title()
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.markdown(f"**{ref}**  \n{items}")
        c2.markdown(f"{o['order_status'].title()}  \n{str(o['order_purchase_timestamp'])[:10]}")
        c3.markdown(f"**R$ {o['total']:.2f}**")
        if st.button("Get help with this order", key=f"ask-{o['order_id']}",
                     use_container_width=True, disabled=bool(st.session_state.pending)):
            shown = f"I need help with order {ref} ({items}, R$ {o['total']:.2f})."
            st.session_state.queued = (shown, f"{shown} Order ID: {o['order_id']}")
            st.rerun()


orders = customer_data.list_orders(customer["id"])
with st.expander(f"📦 Your orders ({len(orders)})", expanded=not st.session_state.history):
    for o in orders:
        order_card(o)

# ---------- hero + suggestions (before the first message) ----------
if not st.session_state.history:
    st.markdown('<div class="hero"><h1>How can we help today?</h1>'
                '<p>Pick an order above, or ask about delivery and returns.</p></div>',
                unsafe_allow_html=True)
    for col, q in zip(st.columns(3), SUGGESTIONS):
        if col.button(q, use_container_width=True):
            st.session_state.queued = (q, q)
            st.rerun()

# ---------- conversation ----------
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tools"):
            with st.expander("What the assistant did"):
                for line in msg["tools"]:
                    st.code(line, language=None)

if st.session_state.pending:
    waiting_for_supervisor()

typed = st.chat_input("Type your message...", disabled=bool(st.session_state.pending))
shown, to_agent = (typed, typed) if typed else st.session_state.pop("queued", (None, None))
if to_agent:
    st.session_state.history.append({"role": "user", "content": shown})
    with st.spinner("Thinking..."):
        run({"messages": [("user", to_agent)]})
    st.rerun()

