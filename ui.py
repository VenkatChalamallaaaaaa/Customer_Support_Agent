import streamlit as st

CSS = """
<style>
#MainMenu, footer, header {visibility: hidden;}
[data-testid="stSidebar"], [data-testid="stSidebarNav"],
[data-testid="collapsedControl"] {display: none;}
.block-container {padding-top: 0; max-width: 820px;}
.navbar {display: flex; justify-content: space-between; align-items: center;
         background: ACCENT; color: white; padding: 16px 24px; margin-bottom: 28px;
         border-radius: 0 0 18px 18px;}
.navbar .brand {font-size: 1.35rem; font-weight: 700;}
.navbar .badge {background: rgba(255,255,255,0.2); padding: 4px 12px;
                border-radius: 999px; font-size: 0.85rem;}
.hero {text-align: center; padding: 28px 0 8px;}
.hero h1 {font-size: 2.1rem; margin-bottom: 4px;}
.hero p {color: #64748b;}
[data-testid="stChatMessage"] {border-radius: 16px; padding: 12px 16px;
                               border: 1px solid rgba(100,116,139,0.25);}
.stButton > button {border-radius: 12px;}
</style>
"""


def apply_theme(accent):
    st.markdown(CSS.replace("ACCENT", accent), unsafe_allow_html=True)


def navbar(brand, badge):
    st.markdown(f'<div class="navbar"><span class="brand">🛍️ {brand}</span>'
                f'<span class="badge">{badge}</span></div>', unsafe_allow_html=True)