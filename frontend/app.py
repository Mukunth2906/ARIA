"""
frontend/app.py — ARIA Streamlit UI
Run: streamlit run frontend/app.py

Requires the FastAPI backend to be running:
  uvicorn backend.main:app --reload --port 8001
"""
import os
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8001")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="ARIA", page_icon="🔐", layout="wide")

# ── Session state defaults ─────────────────────────────────────────────────────
DEFAULTS = {
    "phase":       "input",     # input | review | result | clarify
    "thread_id":   None,
    "agent_state": {},
    "edit_mode":   False,
    "chat_history": [],
    "user_id":     "default",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.aria-banner {
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    border-radius: 14px; padding: 28px 36px; margin-bottom: 28px; color: #fff;
}
.aria-banner h1 { margin:0; font-size:2.2rem; letter-spacing:3px; }
.aria-banner p  { margin:4px 0 0; opacity:.65; font-size:.9rem; }

.verify-card {
    background: #1a1a2e; border-radius: 10px;
    padding: 20px; color: #fff; margin-bottom: 16px;
}
.verify-card h3 { margin:0 0 14px; font-size:.95rem; letter-spacing:1px; color:#a78bfa; }
.chk { display:flex; align-items:center; gap:10px; margin:7px 0; font-size:.88rem; }

.email-card {
    background: #0f172a; border: 1px solid #334155;
    border-radius: 10px; padding: 20px; color: #e2e8f0; margin-bottom: 16px;
}
.email-card h3 { color:#38bdf8; margin:0 0 12px; }
.em  { font-size:.84rem; color:#94a3b8; margin-bottom:4px; }
.em span { color:#e2e8f0; }
.ebody { white-space:pre-wrap; margin-top:12px; font-size:.88rem;
         background:#1e293b; border-radius:6px; padding:12px; }

.bL { background:#166534; color:#bbf7d0; padding:2px 10px; border-radius:12px; font-size:.78rem; }
.bM { background:#854d0e; color:#fef9c3; padding:2px 10px; border-radius:12px; font-size:.78rem; }
.bH { background:#991b1b; color:#fee2e2; padding:2px 10px; border-radius:12px; font-size:.78rem; }

.out-sent   { background:#14532d; color:#bbf7d0; border-radius:8px; padding:18px; text-align:center; font-size:1.05rem; }
.out-block  { background:#7f1d1d; color:#fecaca; border-radius:8px; padding:18px; text-align:center; font-size:1.05rem; }
.out-cancel { background:#1e293b; color:#94a3b8; border-radius:8px; padding:18px; text-align:center; font-size:1.05rem; }

/* Profile card */
.prof-card { background:#1e1e2e; border-radius:10px; padding:14px 18px; color:#c4b5fd; margin-bottom:10px; }
.prof-card h4 { margin:0 0 8px; color:#a78bfa; font-size:.85rem; text-transform:uppercase; letter-spacing:1px; }
.prof-card p  { margin:0; font-size:.82rem; color:#e2e8f0; }
</style>
""", unsafe_allow_html=True)


# ── Banner ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="aria-banner">
  <h1>🔐 ARIA</h1>
  <p>Autonomous Response &amp; Inbox Assistant &nbsp;·&nbsp;
  Gemini + LangGraph &nbsp;·&nbsp; 6-Gate Verification Chain &nbsp;·&nbsp;
  Dynamic User Profile</p>
</div>
""", unsafe_allow_html=True)


# ── API helpers ────────────────────────────────────────────────────────────────
def api_chat(user_id: str, message: str) -> dict:
    r = requests.post(f"{API}/api/chat",
                      json={"user_id": user_id, "message": message}, timeout=90)
    r.raise_for_status(); return r.json()

def api_confirm(thread_id: str, action: str) -> dict:
    r = requests.post(f"{API}/api/confirm",
                      json={"thread_id": thread_id, "action": action}, timeout=90)
    r.raise_for_status(); return r.json()

def api_edit(thread_id: str, user_id: str, original: str, new_body: str) -> dict:
    r = requests.post(f"{API}/api/edit",
                      json={"thread_id": thread_id, "user_id": user_id,
                            "original_input": original, "new_body": new_body}, timeout=90)
    r.raise_for_status(); return r.json()

def api_profile(user_id: str) -> dict:
    try:
        r = requests.get(f"{API}/api/profile/{user_id}", timeout=10)
        r.raise_for_status(); return r.json()
    except Exception: return {}

def api_audit() -> list:
    try:
        r = requests.get(f"{API}/api/audit", timeout=10)
        r.raise_for_status(); return r.json().get("entries", [])
    except Exception: return []


# ── Render helpers ─────────────────────────────────────────────────────────────
def _badge(risk):
    c = {"LOW":"bL","MEDIUM":"bM","HIGH":"bH"}.get(risk, "bM")
    return f'<span class="{c}">{risk}</span>'


def render_verification(s):
    # PII
    if s.get("pii_clean"):          pii = "✅ &nbsp;<b>PII Scan</b> — Clean"
    elif s.get("pii_warning"):      pii = f"⚠️ &nbsp;<b>PII Scan</b> — {', '.join(s['pii_warning'])}"
    else:                           pii = "⏳ &nbsp;<b>PII Scan</b> — Pending"
    # Recipient
    if s.get("recipient_validated"): rcp = f"✅ &nbsp;<b>Recipient</b> — {s.get('recipient_email','?')} ✓"
    elif s.get("validation_error"):  rcp = f"❌ &nbsp;<b>Recipient</b> — {s['validation_error']}"
    else:                            rcp = "⏳ &nbsp;<b>Recipient</b> — Pending"
    # Policy
    if s.get("content_policy_pass"): pol = f"✅ &nbsp;<b>Content Policy</b> — OK (spam {s.get('spam_score',0)}/100)"
    elif s.get("policy_violations"): pol = f"⚠️ &nbsp;<b>Content Policy</b> — {'; '.join(s['policy_violations'])}"
    else:                            pol = "⏳ &nbsp;<b>Content Policy</b> — Pending"
    # Risk
    risk = s.get("overall_risk", "UNKNOWN")
    ico = "✅" if risk == "LOW" else "⚠️" if risk == "MEDIUM" else "❌"
    ris = f"{ico} &nbsp;<b>Risk</b> — {_badge(risk)}"
    # Confidence
    conf = s.get("confidence", 0)
    conf_row = f"{'✅' if conf>=0.6 else '⚠️'} &nbsp;<b>Confidence</b> — {conf:.0%}"
    # Block
    blk = f'<div class="chk" style="color:#f87171">🚫 <b>BLOCKED</b> — {s.get("block_reason","")}</div>' if s.get("blocked") else ""

    st.markdown(f"""
    <div class="verify-card">
      <h3>🔐 VERIFICATION CHAIN</h3>
      <div class="chk">{conf_row}</div>
      <div class="chk">{pii}</div>
      <div class="chk">{rcp}</div>
      <div class="chk">{pol}</div>
      <div class="chk">{ris}</div>
      {blk}
    </div>
    """, unsafe_allow_html=True)


def render_preview(s):
    body_escaped = s.get("body_draft", "").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f"""
    <div class="email-card">
      <h3>📧 Email Preview</h3>
      <div class="em">To: <span>{s.get('recipient_name','')} &lt;{s.get('recipient_email','')}&gt;</span></div>
      <div class="em">Subject: <span>{s.get('subject','')}</span></div>
      <div class="ebody">{body_escaped}</div>
    </div>
    """, unsafe_allow_html=True)


# ── Sidebar: user ID + profile ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 👤 User")
    st.session_state.user_id = st.text_input("User ID", value=st.session_state.user_id)

    st.markdown("---")
    st.markdown("### 📋 Profile")
    profile = api_profile(st.session_state.user_id)
    section_labels = {
        "gmail_section":     "📧 Gmail",
        "calendar_section":  "📅 Calendar",
        "food_section":      "🍽️ Food",
        "travel_section":    "🚗 Travel",
        "user_info_section": "👤 About",
        "contacts_section":  "📇 Contacts",
    }
    has_any = False
    for key, label in section_labels.items():
        val = profile.get(key, "")
        if val:
            has_any = True
            st.markdown(f"""<div class="prof-card"><h4>{label}</h4><p>{val}</p></div>""",
                        unsafe_allow_html=True)
    if not has_any:
        st.caption("No profile data yet. It builds as you use ARIA.")

    if st.button("🔄 Refresh profile"):
        st.rerun()


# ── Main layout ────────────────────────────────────────────────────────────────
left, right = st.columns([1, 1.4], gap="large")

# ════════════════════════════════════════════════════════
# LEFT — Chat
# ════════════════════════════════════════════════════════
with left:
    st.markdown("### 💬 Ask ARIA")
    st.caption("*Send an email to priya@company.com about the project deadline*")

    # Chat history
    for msg in st.session_state.chat_history:
        role_icon = "🧑" if msg["role"] == "user" else "🤖"
        with st.container():
            st.markdown(f"**{role_icon} {msg['role'].title()}:** {msg['content']}")

    if st.session_state.phase == "input":
        user_input = st.text_area("Your request", height=120, label_visibility="collapsed",
                                  placeholder="e.g. Mail ravi@acme.com about the Q2 report…")
        if st.button("🚀 Send to ARIA", type="primary", use_container_width=True):
            if not user_input.strip():
                st.warning("Type a request first.")
            else:
                st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})
                with st.spinner("⚙️ Running 6-gate verification chain…"):
                    try:
                        res = api_chat(st.session_state.user_id, user_input.strip())
                        st.session_state.thread_id   = res["thread_id"]
                        st.session_state.agent_state = res["state"]
                        st.session_state.user_input  = user_input.strip()

                        if res.get("needs_clarify"):
                            st.session_state.chat_history.append(
                                {"role": "assistant", "content": res["reply"]})
                            st.session_state.phase = "input"   # let user respond
                        elif res["state"].get("blocked"):
                            st.session_state.phase = "result"
                        else:
                            st.session_state.phase = "review"
                        st.rerun()
                    except requests.exceptions.ConnectionError:
                        st.error(f"Cannot reach API at {API}. Start the backend with: `uvicorn backend.main:app --reload --port 8001`")
                    except Exception as e:
                        st.error(f"Error: {e}")

    elif st.session_state.phase in ("review", "result"):
        st.text_area("Your request", value=st.session_state.get("user_input", ""),
                     height=120, disabled=True, label_visibility="collapsed")
        if st.button("🔄 New Request", use_container_width=True):
            for k in list(DEFAULTS.keys()):
                st.session_state[k] = DEFAULTS[k]
            st.session_state.chat_history = []
            st.rerun()


# ════════════════════════════════════════════════════════
# RIGHT — Verification + Preview + Actions
# ════════════════════════════════════════════════════════
with right:

    if st.session_state.phase == "input":
        st.markdown("""
        <div style="background:#1e293b;border-radius:10px;padding:36px;
        text-align:center;color:#475569;margin-top:44px">
          <div style="font-size:2.8rem">🔐</div>
          <div style="margin-top:10px;font-size:.9rem">6-gate verification chain<br>will appear here</div>
        </div>""", unsafe_allow_html=True)

    elif st.session_state.phase == "review":
        s = st.session_state.agent_state
        render_verification(s)

        if st.session_state.get("edit_mode"):
            st.markdown("##### ✏️ Edit Email Body")
            new_body = st.text_area("Body", value=s.get("body_draft", ""), height=200,
                                    label_visibility="collapsed")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔄 Re-verify", type="primary", use_container_width=True):
                    with st.spinner("Re-running verification…"):
                        try:
                            res = api_edit(st.session_state.thread_id,
                                          st.session_state.user_id,
                                          st.session_state.get("user_input", ""),
                                          new_body)
                            st.session_state.thread_id   = res["thread_id"]
                            st.session_state.agent_state = res["state"]
                            st.session_state.edit_mode   = False
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
            with c2:
                if st.button("← Back", use_container_width=True):
                    st.session_state.edit_mode = False
                    st.rerun()
        else:
            render_preview(s)
            st.markdown("---")
            st.markdown("**Ready to send?**")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ Confirm & Send", type="primary", use_container_width=True):
                    with st.spinner("Final safety check → sending…"):
                        try:
                            res = api_confirm(st.session_state.thread_id, "confirm")
                            st.session_state.agent_state = res["state"]
                            st.session_state.phase = "result"
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
            with c2:
                if st.button("✏️ Edit", use_container_width=True):
                    st.session_state.edit_mode = True
                    st.rerun()
            with c3:
                if st.button("❌ Cancel", use_container_width=True):
                    with st.spinner("Cancelling…"):
                        try:
                            res = api_confirm(st.session_state.thread_id, "cancel")
                            st.session_state.agent_state = res["state"]
                            st.session_state.phase = "result"
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

    elif st.session_state.phase == "result":
        s = st.session_state.agent_state
        render_verification(s)

        if s.get("send_success"):
            st.markdown(f"""<div class="out-sent">
              ✅ <b>EMAIL SENT SUCCESSFULLY</b><br>
              <small>Message ID: {s.get('gmail_message_id','—')}</small><br>
              <small>Audit entry #{s.get('audit_entry_id','—')}</small>
            </div>""", unsafe_allow_html=True)
        elif s.get("cancelled"):
            st.markdown(f"""<div class="out-cancel">
              🚫 <b>CANCELLED BY USER</b><br>
              <small>Audit entry #{s.get('audit_entry_id','—')}</small>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div class="out-block">
              ❌ <b>BLOCKED</b><br>
              <small>{s.get('block_reason','Unknown')}</small><br>
              <small>Audit #{s.get('audit_entry_id','—')}</small>
            </div>""", unsafe_allow_html=True)

        if not s.get("cancelled"):
            render_preview(s)


# ── Audit log (bottom) ────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("📋 Audit Log", expanded=False):
    entries = api_audit()
    if not entries:
        st.info("No audit entries yet.")
    else:
        for e in entries:
            outcome = e.get("outcome", "?")
            ico = {"SENT":"🟢","BLOCKED":"🔴","CANCELLED_BY_USER":"🟡",
                   "CLARIFICATION_REQUESTED":"🔵"}.get(outcome, "⚪")
            cols = st.columns([0.4, 1.8, 1.8, 2, 1.2, 1.2])
            cols[0].markdown(f"**#{e.get('id','?')}**")
            cols[1].markdown(e.get("timestamp","")[:19].replace("T"," "))
            cols[2].markdown(f"`{e.get('recipient','N/A')}`")
            cols[3].markdown(e.get("subject","N/A")[:40])
            cols[4].markdown(_badge(e.get("risk_level","?")), unsafe_allow_html=True)
            cols[5].markdown(f"{ico} {outcome}")
            st.markdown("<hr style='margin:2px 0;border-color:#1e293b'>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", key="ref_audit"):
            st.rerun()
