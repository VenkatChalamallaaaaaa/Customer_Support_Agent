import streamlit as st
import shared
import ui

st.set_page_config(page_title="Support Console", page_icon="🛡️",
                   layout="centered", initial_sidebar_state="collapsed")
ui.apply_theme("#0f172a")
ui.navbar("Support Console", "Supervisor")


@st.fragment(run_every=2)
def console():
    items = shared.list_pending()
    st.subheader(f"Refunds awaiting approval ({len(items)})")
    if not items:
        st.info("Nothing waiting. This page refreshes automatically.")
    for thread_id, p in items:
        with st.container(border=True):
            st.markdown(f"**Order** `{p['order_id']}`")
            c1, c2 = st.columns(2)
            c1.metric("Amount", f"R$ {p['amount']}")
            c2.metric("Reason", p["reason"].replace("_", " "))
            for note in p["policy_notes"]:
                st.caption(f"• {note}")
            a, d = st.columns(2)
            if a.button("✅ Approve", key=f"a-{thread_id}", type="primary",
                        use_container_width=True):
                shared.decide(thread_id, True)
                st.rerun()
            if d.button("❌ Decline", key=f"d-{thread_id}", use_container_width=True):
                shared.decide(thread_id, False)
                st.rerun()

    st.subheader("Recent decisions")
    rows = shared.recent()
    if not rows:
        st.caption("No decisions yet.")
    for r in rows:
        verdict = "✅ Approved" if r["approved"] else "❌ Declined"
        st.write(f"`{r['time']}` {verdict}: order `{r['order_id'][:8]}…` R$ {r['amount']}")


console()