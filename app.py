"""
Aplazo Payment Orchestrator — Senior PM Case Readout
Run: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import math
from orchestrator import (
    PaymentOrchestrator, Transaction,
    ISSUER_PSP_AR, PSP_FEES, HARD_DECLINE_PATTERNS,
)


# ─────────────────────────────────────────────────────────────────────────────
# FLOW VISUALIZATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _node(icon, title, subtitle, state):
    colors = {
        "green":  ("#dcfce7", "#22c55e", "#166534"),
        "red":    ("#fee2e2", "#ef4444", "#991b1b"),
        "amber":  ("#fffbeb", "#f59e0b", "#92400e"),
        "gray":   ("#f3f4f6", "#d1d5db", "#9ca3af"),
        "idle":   ("#f8fafc", "#cbd5e1", "#64748b"),
    }
    bg, border, text = colors.get(state, colors["idle"])
    return f"""
<div style="display:flex;flex-direction:column;align-items:center;min-width:88px;max-width:100px;">
  <div style="width:52px;height:52px;border-radius:50%;background:{bg};border:2.5px solid {border};
       display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:5px;
       box-shadow:0 1px 4px rgba(0,0,0,0.08);">{icon}</div>
  <div style="font-size:11px;font-weight:700;color:{text};text-align:center;line-height:1.3;">{title}</div>
  <div style="font-size:10px;color:#6b7280;text-align:center;margin-top:2px;line-height:1.3;min-height:28px;">{subtitle}</div>
</div>"""

def _arrow(state):
    color = {"green":"#22c55e","red":"#ef4444","amber":"#f59e0b","gray":"#d1d5db","idle":"#e2e8f0"}.get(state,"#e2e8f0")
    return f'<div style="flex:1;min-width:16px;height:2px;background:{color};margin-top:-30px;margin-left:-2px;margin-right:-2px;"></div>'

def build_flow_html(dec, tx, issuer, hard_stopped, retry_capped, has_issuer):
    """Build a horizontal decision-flow pipeline showing which gates were hit."""

    # Determine state of each gate
    s_input   = "green"
    s_hard    = "red"   if hard_stopped and dec.stop_reason and "hard decline" in dec.stop_reason else "green"
    s_cap     = "red"   if retry_capped else ("gray" if hard_stopped else "green")
    s_cron    = "amber" if tx.is_cron and not hard_stopped and not retry_capped else \
                ("gray" if (hard_stopped or retry_capped) else "green")
    s_bin     = "green" if has_issuer and not hard_stopped and not retry_capped else \
                ("amber" if not hard_stopped and not retry_capped else "gray")
    s_score   = "gray" if (hard_stopped or retry_capped) else "green"
    s_out     = "red"  if (hard_stopped or retry_capped) else "green"

    # Node labels
    n_hard  = ("BLOCKED", "hard decline") if s_hard == "red" else ("✓ Passed", "no hard error")
    n_cap   = ("BLOCKED", f"attempt {tx.attempt_number}/{dec.max_attempts}") if s_cap == "red" else \
              ("—", "skipped") if s_cap == "gray" else ("✓ Passed", f"attempt {tx.attempt_number}")
    n_cron  = ("⏰ Cron", "restricted routing") if s_cron == "amber" else \
              ("—", "skipped") if s_cron == "gray" else ("✓ Standard", "user-present")
    n_bin   = ("✓ Matched", issuer[:14] if issuer else "") if s_bin == "green" else \
              ("—", "skipped") if s_bin == "gray" else ("⚠ No match", "global fallback")
    n_score = ("—", "skipped") if s_score == "gray" else ("✓ Scored", dec.recommended_psp.upper())
    n_out   = ("🚫 STOP", dec.stop_reason[:22] if dec.stop_reason else "") if s_out == "red" else \
              ("✅ ROUTE", dec.recommended_psp.upper())

    arrow_states = [s_hard, s_cap, s_cron, s_bin, s_score, s_out]

    html = '<div style="overflow-x:auto;padding:16px 0 8px;">'
    html += '<div style="display:flex;align-items:center;gap:0;min-width:660px;">'
    html += _node("📨", "Input", "transaction<br>received", s_input)
    for (state, (lbl, sub), title) in [
        (s_hard,  n_hard,  "Hard Decline<br>Check"),
        (s_cap,   n_cap,   "Retry Cap<br>Gate"),
        (s_cron,  n_cron,  "Channel<br>Type"),
        (s_bin,   n_bin,   "BIN / Issuer<br>Lookup"),
        (s_score, n_score, "PSP<br>Scoring"),
        (s_out,   n_out,   "Final<br>Decision"),
    ]:
        html += _arrow(state)
        html += _node(
            {"green":"✅","red":"🛑","amber":"⚠️","gray":"⬜","idle":"⬜"}.get(state,"⬜"),
            title, f"{lbl}<br><span style='font-size:9px'>{sub}</span>", state
        )
    html += '</div></div>'

    # Legend
    html += '''<div style="display:flex;gap:16px;margin-top:10px;flex-wrap:wrap;font-size:11px;color:#6b7280;">
      <span>🟢 Passed &nbsp; 🔴 Blocked &nbsp; 🟡 Modified &nbsp; ⬜ Skipped</span>
    </div>'''
    return html

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aplazo Payment Orchestrator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
  .metric-box {
    background: #f8f9fb;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    border-left: 4px solid #1f77b4;
    margin-bottom: 0.75rem;
  }
  .formula-box {
    background: #1a1a2e;
    color: #e2e8f0;
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    font-family: "SF Mono", monospace;
    font-size: 0.92rem;
    margin: 0.8rem 0;
    line-height: 1.8;
  }
  .formula-box .highlight { color: #7ec8e3; font-weight: 700; }
  .formula-box .comment  { color: #94a3b8; font-style: italic; }
  .psp-badge {
    display: inline-block;
    background: #0068c9;
    color: white;
    padding: 0.25rem 0.8rem;
    border-radius: 20px;
    font-size: 1rem;
    font-weight: 700;
  }
  .stop-badge {
    display: inline-block;
    background: #d62728;
    color: white;
    padding: 0.25rem 0.8rem;
    border-radius: 20px;
    font-size: 1rem;
    font-weight: 600;
  }
  .callout-amber {
    background: #fffbeb;
    border-left: 4px solid #f59e0b;
    border-radius: 0 8px 8px 0;
    padding: 0.8rem 1rem;
    font-size: 0.88rem;
    color: #92400e;
    margin: 0.6rem 0;
  }
  .callout-green {
    background: #f0fdf4;
    border-left: 4px solid #22c55e;
    border-radius: 0 8px 8px 0;
    padding: 0.8rem 1rem;
    font-size: 0.88rem;
    color: #166534;
    margin: 0.6rem 0;
  }
  .callout-red {
    background: #fef2f2;
    border-left: 4px solid #ef4444;
    border-radius: 0 8px 8px 0;
    padding: 0.8rem 1rem;
    font-size: 0.88rem;
    color: #991b1b;
    margin: 0.6rem 0;
  }
  .callout-blue {
    background: #eff6ff;
    border-left: 4px solid #3b82f6;
    border-radius: 0 8px 8px 0;
    padding: 0.8rem 1rem;
    font-size: 0.88rem;
    color: #1e40af;
    margin: 0.6rem 0;
  }
  .note-box {
    background: #fff8e1;
    border-left: 4px solid #f9a825;
    border-radius: 6px;
    padding: 0.7rem 1rem;
    font-size: 0.88rem;
    margin-top: 0.5rem;
  }
  table.styled { width:100%; border-collapse:collapse; font-size:0.85rem; }
  table.styled th {
    background:#f1f5f9; padding:8px 12px; text-align:left;
    border-bottom:2px solid #e2e8f0; font-size:0.75rem;
    text-transform:uppercase; letter-spacing:0.05em; color:#475569;
  }
  table.styled td { padding:8px 12px; border-bottom:1px solid #f1f5f4; color:#374151; }
  table.styled tr:hover td { background:#fafbff; }
  .ok   { color:#16a34a; font-weight:700; }
  .warn { color:#dc2626; font-weight:700; }
  .muted { color:#6b7280; font-size:0.82rem; }
  h4 { color: #1a1a2e; margin: 1.2rem 0 0.4rem; }

  /* Push tabs below Streamlit's sticky header */
  .stTabs [data-baseweb="tab-list"] {
    margin-top: 1rem;
  }

  /* ── Global accent override (replaces Streamlit's default red) ── */
  :root {
    --primary-color: #7ec8e3 !important;
  }
  /* Primary buttons anywhere */
  .stButton > button[kind="primary"],
  .stButton > button[data-testid="stFormSubmitButton"],
  button[kind="primary"] {
    background: #7ec8e3 !important;
    color: #1a1a2e !important;
    border: none !important;
    font-weight: 700 !important;
  }
  .stButton > button[kind="primary"]:hover,
  button[kind="primary"]:hover {
    background: #5db8d8 !important;
    color: #1a1a2e !important;
  }
  /* Slider filled/active track — global */
  [data-testid="stSlider"] [data-testid="stSliderTrack"] > div:nth-child(2),
  [data-testid="stSlider"] > div > div > div > div:nth-child(2) {
    background: #7ec8e3 !important;
  }
  /* Slider thumb — global */
  [data-testid="stSlider"] [role="slider"] {
    background: #7ec8e3 !important;
    border-color: #7ec8e3 !important;
  }

  /* ── Sidebar theme ────────────────────────────────────────── */
  [data-testid="stSidebar"] {
    background-color: #1a1a2e !important;
  }
  [data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
  }
  /* Slider track */
  [data-testid="stSidebar"] [data-testid="stSlider"] [data-testid="stSliderTrack"] > div:first-child {
    background: #2d2d4e !important;
  }
  [data-testid="stSidebar"] [data-testid="stSlider"] [data-testid="stSliderTrack"] > div:nth-child(2) {
    background: #7ec8e3 !important;
  }
  /* Slider thumb/knob */
  [data-testid="stSidebar"] [data-testid="stSlider"] [role="slider"] {
    background: #7ec8e3 !important;
    border-color: #7ec8e3 !important;
  }
  /* Buttons */
  [data-testid="stSidebar"] .stButton > button {
    background: #7ec8e3 !important;
    color: #1a1a2e !important;
    border: none !important;
    font-weight: 700 !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: #5db8d8 !important;
    color: #1a1a2e !important;
  }
  /* Divider */
  [data-testid="stSidebar"] hr {
    border-color: #2d2d4e !important;
  }
  /* Select box / dropdown */
  [data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
    background: #2d2d4e !important;
    border-color: #3d3d5e !important;
    color: #e2e8f0 !important;
  }
  /* Caption / muted text keep slightly dimmer */
  [data-testid="stSidebar"] small, [data-testid="stSidebar"] .stCaption {
    color: #94a3b8 !important;
  }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Aplazo Payment Orchestrator")
    st.caption("Senior PM Case · March 2026 data")
    st.divider()

    st.subheader("Optimization Knob")
    knob = st.slider(
        label="Min Cost  ←——→  Max Acceptance",
        min_value=0.0, max_value=1.0, value=0.5, step=0.05,
        help="Controls the weight between fee minimization (0.0) and approval rate maximization (1.0). See the Formula tab for the scoring math.",
    )
    if knob <= 0.25:
        st.info("**Cost-first mode** — routes to cheapest PSP unless issuer signal strongly overrides.")
    elif knob >= 0.75:
        st.success("**Acceptance-first mode** — routes strictly by issuer-PSP historical Approval Rate matrix.")
    else:
        st.warning("**Balanced mode (recommended)** — weighted blend of cost and Approval Rate.")

    st.divider()
    st.subheader("Volume Guardrail")
    guardrail_pct = st.slider(
        label="Minimum traffic share per secondary PSP",
        min_value=0, max_value=30, value=10, step=5,
        format="%d%%",
        help="Prevents 100% concentration in one PSP. 10% means psp-c can receive at most 90% of traffic.",
    )
    guardrail = guardrail_pct / 100

    st.divider()
    st.caption("Tabs: Simulator · Formula · Data Findings · Product Story · Observability")

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_sim, tab_formula, tab_data, tab_product, tab_obs = st.tabs([
    "Simulator",
    "Formula",
    "Data",
    "Product",
    "Observability",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_sim:
    st.header("Transaction Simulator")
    st.caption("Simulate any card transaction and inspect the orchestrator's full decision — including the math behind it.")

    ISSUERS = [
        "Unknown / No BIN data",
        "Nu MX", "Bancoppel", "BBVA", "Banco Santander",
        "Banco Azteca", "Banco Nacional de MX", "HSBC",
        "Mercado Libre", "Uala", "Klar", "Banregio",
        "Banco Mercantil del Norte", "Banco Compartamos",
        "Stori", "Banca Afirme", "Scotiabank",
        "Bradescard", "Liverpool",
    ]
    GATEWAYS = [
        "nextpayment", "user-dashboard-nextpayment", "checkout",
        "user-dashboard-wholepayment", "wholepayment",
        "cron", "admin-dashboard-nextpayment",
    ]
    ERROR_OPTIONS = [
        "None (first attempt / no prior error)",
        "The card doesn't have sufficient funds",
        "Insufficient funds",
        "Fraud risk detected by anti-fraud system",
        "Card country not authorized for this merchant",
        "The card was declined by the bank",
        "The card has expired",
        "High risk transaction",
        "Bank authorization is required for this charge",
        "Invalid card or card type",
        "The card was reported as lost",
        "Other (type below)",
    ]

    col_form, col_out = st.columns([1, 1.3], gap="large")

    with col_form:
        with st.form("tx_form"):
            amount     = st.number_input("Transaction Amount (MXN)", min_value=1.0, max_value=50_000.0, value=850.0, step=50.0)
            issuer_sel = st.selectbox("Card Issuer (from BIN lookup)", ISSUERS)
            gateway    = st.selectbox("Collection Gateway", GATEWAYS)
            attempt_n  = st.number_input("Current Attempt Number", min_value=1, max_value=10, value=1, step=1)
            error_sel  = st.selectbox("Last Error Message (if retry)", ERROR_OPTIONS)
            custom_err = ""
            if error_sel == "Other (type below)":
                custom_err = st.text_input("Custom error message")
            submitted = st.form_submit_button("⚡ Route Transaction", width="stretch", type="primary")

    with col_out:
        if not submitted:
            st.markdown("""
<div class="callout-blue">
Fill in the form on the left and click <strong>Route Transaction</strong> to see the orchestrator's decision, the scoring math, and the reasoning chain.
</div>""", unsafe_allow_html=True)
            st.markdown("")
            st.markdown("**PSP Fee Reference**")
            for psp, fee in sorted(PSP_FEES.items(), key=lambda x: x[1]):
                st.markdown(f"- `{psp}` — **{fee*100:.2f}%** on approved transactions")
        else:
            issuer    = None if issuer_sel == "Unknown / No BIN data" else issuer_sel
            error_msg = None
            if error_sel not in ("None (first attempt / no prior error)", "Other (type below)"):
                error_msg = error_sel
            elif error_sel == "Other (type below)" and custom_err:
                error_msg = custom_err

            tx   = Transaction(amount=amount, issuer=issuer, gateway=gateway,
                               is_cron="cron" in gateway.lower(),
                               error_message=error_msg, attempt_number=attempt_n)
            orch = PaymentOrchestrator(knob=knob, volume_guardrail=guardrail)
            dec  = orch.route(tx)

            hard_stopped = dec.recommended_psp == "none"

            # ── Result header
            if hard_stopped:
                st.markdown('<span class="stop-badge">🚫 DO NOT RETRY</span>', unsafe_allow_html=True)
                st.markdown(f"**Stop reason:** {dec.stop_reason}")
            else:
                st.markdown(
                    f'Recommended PSP &nbsp; <span class="psp-badge">{dec.recommended_psp.upper()}</span>',
                    unsafe_allow_html=True)
                st.markdown("")
                c1, c2, c3 = st.columns(3)
                c1.metric("Fee if approved", f"${orch.expected_cost(amount, dec.recommended_psp):.2f} MXN",
                          f"{PSP_FEES[dec.recommended_psp]*100:.2f}%")
                if dec.expected_ar:
                    c2.metric("Expected Approval Rate", f"{dec.expected_ar*100:.1f}%", "issuer-level signal")
                else:
                    c2.metric("Expected Approval Rate", "—", "no BIN match")
                c3.metric("Max Attempts", str(dec.max_attempts))

            st.divider()

            # ── Scoring math (live)
            if not hard_stopped and issuer and issuer.lower() in ISSUER_PSP_AR:
                st.markdown("**Live Scoring Math**")
                issuer_key = issuer.lower()
                ar_row = ISSUER_PSP_AR[issuer_key]
                all_psps = list(PSP_FEES.keys())
                min_fee = min(PSP_FEES.values())
                max_fee = max(PSP_FEES.values())
                rows = []
                for psp in all_psps:
                    fee = PSP_FEES[psp]
                    cost_score = 1 - (fee - min_fee) / (max_fee - min_fee + 1e-9)
                    ar_score   = ar_row.get(psp, 0.498 if psp == "psp-o" else 0.330)
                    score = (1 - knob) * cost_score + knob * ar_score
                    rows.append({"PSP": psp,
                                 f"AR ({issuer})": f"{ar_score*100:.1f}%",
                                 "Cost Score": f"{cost_score:.3f}",
                                 "AR Score": f"{ar_score:.3f}",
                                 f"Final Score (knob={knob})": f"{score:.4f}",
                                 "Selected": "✅" if psp == dec.recommended_psp else ""})
                df_scores = pd.DataFrame(rows).set_index("PSP")
                st.dataframe(df_scores, width="stretch")
                st.markdown(f'<div class="muted">Score = ({1-knob:.2f} × cost_score) + ({knob:.2f} × ar_score)</div>', unsafe_allow_html=True)

            st.divider()

            # ── Retry policy
            st.markdown("**Retry Policy**")
            retry_icon = "✅" if dec.retry else "🚫"
            st.markdown(f"""
<div class="metric-box">
<b>{retry_icon} Retry:</b> {dec.retry} &nbsp;|&nbsp;
<b>Next PSP:</b> {dec.retry_on_psp or '—'} &nbsp;|&nbsp;
<b>Fallback order:</b> {' → '.join(dec.fallback_psps) if dec.fallback_psps else '—'}<br>
<b>Max attempts:</b> {dec.max_attempts} &nbsp;|&nbsp;
<b>Stop reason:</b> {dec.stop_reason or '—'}
</div>""", unsafe_allow_html=True)

            # ── Reasoning chain
            st.markdown("**Decision Reasoning Chain**")
            reasons = []
            if hard_stopped and error_msg:
                reasons.append(("🔴 Hard Decline Interceptor",
                    f'Error pattern matched a permanent failure class (0% recovery rate across 771k+ historical attempts). '
                    f'Retrying would waste submission overhead with zero expected value.'))
            elif dec.recommended_psp == "none":
                reasons.append(("🔴 Retry Cap",
                    f'Attempt #{attempt_n} exceeds the policy ceiling of {dec.max_attempts} for this context. '
                    f'Historical Approval Rate at this retry depth is below 20%.'))
            if issuer and issuer.lower() in ISSUER_PSP_AR and not hard_stopped:
                ar_row = ISSUER_PSP_AR[issuer.lower()]
                ar_str = "  |  ".join(f"{p}: {v*100:.0f}%" for p, v in sorted(ar_row.items(), key=lambda x: -x[1]))
                reasons.append(("📊 Issuer-PSP Matrix",
                    f"Historical approval rates for {issuer}: {ar_str}. "
                    f"Routing to highest-scoring PSP given knob={knob}."))
            if tx.is_cron and not hard_stopped:
                reasons.append(("⏰ Cron Channel Override",
                    "Gateway is cron — user is not present. psp-e excluded (29–35% Approval Rate on batch). "
                    "Retry cap reduced to 3. Cost-side of knob weighted more heavily."))
            if issuer and issuer.lower() in ("bradescard", "liverpool"):
                reasons.append(("⚠️ Critically Low Issuer",
                    f"{issuer} has <26% baseline Approval Rate on all PSPs. Retry cap set to 2. "
                    "Consider alternative collection channel (WhatsApp/SPEI link) before further card retries."))
            if not issuer and not hard_stopped:
                reasons.append(("❓ No BIN Signal",
                    "psp-o and psp-d have no BIN logging in event data — cannot rank them by issuer Approval Rate. "
                    "Defaulting to psp-c (lowest fee) with global Approval Rate proxy scores for psp-o/psp-d."))
            if not hard_stopped:
                knob_txt = ("Cost-first: cheapest PSP dominates unless issuer Approval Rate delta is large." if knob <= 0.25
                            else "Acceptance-first: highest issuer-PSP Approval Rate drives the choice." if knob >= 0.75
                            else "Balanced: cost efficiency and issuer Approval Rate weighted equally.")
                reasons.append(("🎛️ Knob Logic", f"Knob={knob:.2f} → {knob_txt}"))
                reasons.append(("🛡️ Volume Guardrail",
                    f"{guardrail_pct}% minimum floor per secondary PSP prevents full concentration risk. "
                    f"psp-c capped at {100-guardrail_pct}% of total traffic."))

            for title, body in reasons:
                st.markdown(f"""
<div class="metric-box">
<b>{title}</b><br>
<span style="font-size:0.87rem;color:#374151">{body}</span>
</div>""", unsafe_allow_html=True)

            for note in dec.notes:
                st.markdown(f'<div class="note-box">⚠️ {note}</div>', unsafe_allow_html=True)

    # ── Full-width decision flow ─────────────────────────────────────────────
    if submitted:
        st.divider()
        st.markdown("#### Decision Flow — how the orchestrator reached this output")
        st.caption("Each gate in the pipeline is evaluated in order. The first gate that blocks stops the chain.")
        hard_stopped_flow = dec.recommended_psp == "none"
        retry_capped_flow = hard_stopped_flow and dec.stop_reason and "retry cap" in dec.stop_reason
        hard_declined_flow = hard_stopped_flow and not retry_capped_flow
        has_issuer_flow = bool(issuer and issuer.lower() in ISSUER_PSP_AR)
        st.markdown(
            build_flow_html(dec, tx, issuer, hard_declined_flow, retry_capped_flow, has_issuer_flow),
            unsafe_allow_html=True
        )
        st.markdown("")
        # Gate-by-gate plain-English explanation
        with st.expander("📖 What each gate means — explain this live to the panel"):
            st.markdown("""
**Gate 1 — Hard Decline Check**
Scans the last error message against 12 known permanent failure patterns (insufficient funds, fraud, expired card, etc.).
If matched → immediate stop. Zero retry value, zero fee wasted. 518,075 "insufficient funds" attempts in the data had 0% recovery rate.

**Gate 2 — Retry Cap**
Checks how many times this installment has already been attempted. Caps vary by context:
- Standard user-initiated: 5 attempts (Approval Rate drops below 20% at attempt 6)
- Cron batch: 3 attempts (degrades faster with no user-recovery option)
- Critically low issuers (Bradescard, Liverpool): 2 attempts max

**Gate 3 — Channel Type (Cron?)**
If the gateway is `cron`, the engine applies restricted routing: psp-e is excluded (29–35% Approval Rate on cron), retry cap tightens, and cost-efficiency is weighted more heavily. Cron is 47% of volume but 30.4% baseline Approval Rate — it needs its own logic.

**Gate 4 — BIN / Issuer Lookup**
Checks if the card's BIN matches a known issuer in our performance matrix. If matched → issue-specific PSP scores applied. If not matched (or PSP doesn't log BIN) → falls back to global Approval Rate proxies. Only 21.3% of rows matched a BIN in the data.

**Gate 5 — PSP Scoring**
Scores every PSP using: `Score = (knob × AR_score) + (1−knob × cost_efficiency_score)`. The highest-scoring PSP clears the volume guardrail check and becomes the recommendation.

**Gate 6 — Final Decision**
Either routes the transaction to the winning PSP with a full retry policy, or emits a STOP signal with an explicit reason. Every decision is fully auditable — no black box.
""")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCORING FORMULA
# ══════════════════════════════════════════════════════════════════════════════
with tab_formula:
    st.header("Scoring Formula & Value Definition")
    st.markdown("""
The orchestrator must define what **"value"** means. Value is not just approval rate, nor just low fees.
Value is **Net Recovery Margin** — the expected revenue recovered after processing cost, weighted by the probability
of approval. The engine scores every eligible PSP with the following formula:
""")

    st.markdown("""
<div class="formula-box">
<span class="highlight">Score(PSP)</span> = (<span class="highlight">knob</span> × AR_score<sub>PSP, Issuer</sub>)
                 + (<span class="highlight">1 − knob</span> × CostEfficiency_score<sub>PSP</sub>)
<br><br>
<span class="comment">where:</span><br>
  AR_score        = historical approval rate for this issuer on this PSP (from Step 1b matrix)<br>
  CostEfficiency  = 1 − ( (fee_PSP − fee_min) / (fee_max − fee_min) )  <span class="comment">← normalized 0–1, higher = cheaper</span><br>
  knob            = operator-set parameter ∈ [0.0, 1.0]
<br><br>
<span class="comment">Route to:  argmax_PSP Score(PSP),  subject to volume_guardrail constraint</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("### Why this formula is defensible")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
<div class="callout-green">
<b>When knob = 1.0 (Max Acceptance)</b><br>
The cost term drops to zero. The engine sorts purely by the highest historical Approval Rate for this issuer.
Example: Nu MX → psp-c (81.2%) over psp-e (15.8%).
</div>
<div class="callout-amber">
<b>When knob = 0.0 (Min Cost)</b><br>
The Approval Rate term drops to zero. The engine routes to the lowest fee PSP (psp-c at 1.55%)
regardless of issuer-level Approval Rate differences.
</div>""", unsafe_allow_html=True)
    with col2:
        st.markdown("""
<div class="callout-blue">
<b>When knob = 0.5 (Balanced default)</b><br>
The engine evaluates the mathematical frontier. If psp-e has 2% higher Approval Rate than psp-c
but charges 8.4% more in fees (1.68% vs 1.55%), the balanced knob penalizes psp-e
when the marginal cost exceeds the marginal Approval Rate gain.
</div>""", unsafe_allow_html=True)

    st.markdown("### Live Fee Reference")
    fee_df = pd.DataFrame([
        {"PSP": psp, "Fee Rate": f"{fee*100:.2f}%",
         "Cost Score (normalized)": f"{1 - (fee - min(PSP_FEES.values())) / (max(PSP_FEES.values()) - min(PSP_FEES.values()) + 1e-9):.3f}",
         "Example fee on $1,000 MXN": f"${fee*1000:.2f} MXN"}
        for psp, fee in sorted(PSP_FEES.items(), key=lambda x: x[1])
    ]).set_index("PSP")
    st.dataframe(fee_df, width="stretch")

    st.markdown("### Hard Decline Intercept Rule")
    st.markdown("""
Before the scoring formula runs, the engine applies a **zero-cost short-circuit** for permanent failure classes.
Historical data shows these error patterns have **0.00% recovery rate** across 771k+ retry attempts:
""")
    st.markdown("""
<div class="formula-box">
<span class="highlight">IF</span> normalize(error_message) ∈ {
    "insufficient funds", "fraud risk detected",
    "card expired", "card country not authorized",
    "card reported as lost", "exceeded max attempts"
}
<br>
<span class="highlight">THEN</span>  retry = False,  stop_reason = "hard decline",  fee_exposure = $0
<br><br>
<span class="comment">Rationale: retrying hard declines wastes submission overhead, degrades Aplazo's merchant
health score with banking rails, and has zero expected revenue upside.</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("### Retry Cap Policy")
    st.markdown("""
Historical retry analysis (Step 1) shows Approval Rate collapses past attempt 5 for standard flows.
Cron flows degrade faster with no user-recovery option:
""")
    cap_df = pd.DataFrame([
        {"Context": "Standard user-initiated (nextpayment, checkout)", "Max Attempts": 5, "Rationale": "Approval Rate at attempt 6+ falls below 20%"},
        {"Context": "Cron / batch (no user present)", "Max Attempts": 3, "Rationale": "No fallback channel; cost of retries outweighs recovery"},
        {"Context": "Critically low issuer (Bradescard, Liverpool)", "Max Attempts": 2, "Rationale": "<26% baseline Approval Rate — escalate to SPEI/WhatsApp link instead"},
        {"Context": "Any hard decline error", "Max Attempts": 1, "Rationale": "0% recovery rate — stop immediately"},
    ])
    st.dataframe(cap_df, width="stretch", hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DATA FINDINGS
# ══════════════════════════════════════════════════════════════════════════════
with tab_data:
    st.header("Analytical Findings — March 2026 Data")
    st.caption("5,882,702 payment events · 1,121,738 loans · 1,282 BINs · Card-only scope: 5,841,740 rows")

    st.markdown("### Approval Rate Definitions")
    st.markdown("""
<div class="callout-blue">
<b>Attempt-level Approval Rate = approved attempts / terminal attempts</b> → <b>26.25%</b><br>
Low because many installments are retried multiple times; each failure counts as a denominator row.<br><br>
<b>Installment-level Approval Rate = installments with ≥1 approval / total installments</b> → <b>82.51%</b><br>
The "true collection rate" — most loans eventually collect, just not always on the first try.
</div>
""", unsafe_allow_html=True)

    st.markdown("### Finding 1 — PSP Performance")
    psp_df = pd.DataFrame([
        {"PSP": "psp-c", "Attempts": "532,370", "Approval Rate": "73.4%", "Fee": "1.55%", "BIN data": "✅ Yes", "Verdict": "🏆 Primary — best Approval Rate + cheapest fee"},
        {"PSP": "psp-e", "Attempts": "543,413", "Approval Rate": "55.8%", "Fee": "1.68%", "BIN data": "✅ Yes", "Verdict": "Secondary — issuer-specific routing only"},
        {"PSP": "psp-o", "Attempts": "1,549,990", "Approval Rate": "49.8%", "Fee": "1.58%", "BIN data": "❌ No", "Verdict": "⚠️ Overused — 55% of volume, below-average Approval Rate"},
        {"PSP": "psp-d", "Attempts": "203,801", "Approval Rate": "33.0%", "Fee": "1.69%", "BIN data": "❌ No", "Verdict": "🚨 Last resort only — worst Approval Rate + highest fee"},
    ]).set_index("PSP")
    st.dataframe(psp_df, width="stretch")
    st.markdown("""
<div class="callout-amber">
<b>Key insight:</b> psp-o was receiving 54.8% of all card volume but achieves only 49.8% Approval Rate.
psp-c handles 18.8% of volume but generates 25.5% of all approvals. Redistributing volume from psp-o
to psp-c is the single highest-leverage routing change available with zero model complexity.
</div>""", unsafe_allow_html=True)

    st.markdown("### Finding 2 — Credit vs Debit Split (Non-obvious cut)")
    funding_df = pd.DataFrame([
        {"PSP": "psp-c", "Card Type": "Debit", "Approval Rate": "76.7%", "Attempts": "378,590"},
        {"PSP": "psp-c", "Card Type": "Credit", "Approval Rate": "62.4%", "Attempts": "59,964"},
        {"PSP": "psp-c", "Card Type": "Prepaid", "Approval Rate": "77.4%", "Attempts": "27,443"},
        {"PSP": "psp-e", "Card Type": "Debit", "Approval Rate": "42.4%", "Attempts": "10,717"},
        {"PSP": "psp-e", "Card Type": "Credit", "Approval Rate": "29.9%", "Attempts": "3,192"},
    ])
    st.dataframe(funding_df, width="stretch", hide_index=True)
    st.markdown("""
<div class="callout-red">
<b>Counterintuitive finding:</b> psp-c approves debit cards better than credit (76.7% vs 62.4%).
psp-e collapses on credit (29.9%). This suggests psp-e lacks strong connectivity with Mexico's
major credit-issuing banks. Never route credit cards from Nu MX or Banamex to psp-e.
</div>""", unsafe_allow_html=True)

    st.markdown("### Finding 3 — Issuer × PSP Matrix (routing signal)")
    issuer_data = []
    for issuer_name, psps in ISSUER_PSP_AR.items():
        best = max(psps, key=psps.get)
        row = {"Issuer": issuer_name.title()}
        for psp, ar in psps.items():
            row[psp.upper()] = f"{ar*100:.1f}%"
        row["Best PSP"] = best.upper()
        row["Approval Rate Delta (best vs worst)"] = f"{(max(psps.values()) - min(psps.values()))*100:.1f}pp"
        issuer_data.append(row)
    issuer_df = pd.DataFrame(issuer_data).set_index("Issuer")
    st.dataframe(issuer_df, width="stretch")
    st.markdown('<div class="muted">pp = percentage points. Large deltas = high routing leverage for that issuer.</div>', unsafe_allow_html=True)

    st.markdown("### Finding 4 — Cron Gateway (non-obvious cut)")
    gateway_df = pd.DataFrame([
        {"Gateway": "nextpayment", "Approval Rate": "78.8%", "Context": "User actively paying"},
        {"Gateway": "user-dashboard-nextpayment", "Approval Rate": "76.3%", "Context": "User paying via dashboard"},
        {"Gateway": "checkout", "Approval Rate": "69.9%", "Context": "User at checkout"},
        {"Gateway": "cron", "Approval Rate": "30.4%", "Context": "⏰ Automated batch — no user present"},
        {"Gateway": "admin-dashboard-nextpayment", "Approval Rate": "8.2%", "Context": "⚠️ Agent manual retry on already-failed cards"},
    ]).set_index("Gateway")
    st.dataframe(gateway_df, width="stretch")
    st.markdown("""
<div class="callout-amber">
<b>admin-dashboard-nextpayment at 8.2% Approval Rate:</b> This is not a PSP problem — it's a behavioral pattern.
Agents are retrying cards that customers have already blocked or drained. Recommendation: after 2 agent-dashboard
failures, automatically trigger a WhatsApp payment link for SPEI transfer instead of continuing card retries.
</div>""", unsafe_allow_html=True)

    st.markdown("### Finding 5 — Retry Analysis")
    retry_df = pd.DataFrame([
        {"Attempt #": "1", "Approval Rate": "52.9%", "Interpretation": "Baseline — best single-shot AR"},
        {"Attempt #": "2", "Approval Rate": "47.4%", "Interpretation": "Soft declines recovering"},
        {"Attempt #": "3", "Approval Rate": "66.8%", "Interpretation": "Spike — likely PSP switch or card-level reset"},
        {"Attempt #": "4", "Approval Rate": "37.4%", "Interpretation": "Declining — diminishing returns start"},
        {"Attempt #": "5", "Approval Rate": "26.3%", "Interpretation": "Policy cap for standard flows"},
        {"Attempt #": "6", "Approval Rate": "19.3%", "Interpretation": "⛔ Below threshold — stop here"},
        {"Attempt #": "7+", "Approval Rate": "<18%", "Interpretation": "⛔ No recovery value"},
    ])
    st.dataframe(retry_df, width="stretch", hide_index=True)

    st.markdown("### Finding 6 — PSP-switch on retry has no effect")
    st.markdown("""
<div class="callout-blue">
<b>Same PSP retry: 50.6% Approval Rate &nbsp;|&nbsp; Switched PSP retry: 50.5% Approval Rate</b> — statistically identical (Δ = 0.1pp).<br>
This invalidates the common assumption that "routing to a different PSP on retry will rescue the transaction."
The decision engine should focus on <em>error type</em> (hard vs soft decline) rather than PSP-switching.
Route correctly the first time using the issuer matrix.
</div>""", unsafe_allow_html=True)

    st.markdown("### Data Quality Issues Encountered")
    dq_df = pd.DataFrame([
        {"Field": "error_message", "Issue": "6+ variants of same error (e.g. 'insufficient funds', 'INSUFFICIENT_FUNDS', 'fondos insuficientes')", "Fix": "Lowercase + substring matching against canonical set"},
        {"Field": "bin", "Issue": "psp-o and psp-d send no BIN data — 0% match rate on those PSPs", "Fix": "Treat as generic fallbacks; flag as data pipeline gap"},
        {"Field": "payment_type", "Issue": "Case variants, blanks, NaN mixed", "Fix": "str.strip().str.lower() + replace empty with NaN"},
        {"Field": "event_timestamp", "Issue": "Mixed precision: some rows have milliseconds, some don't", "Fix": "format='mixed' in pd.to_datetime()"},
        {"Field": "psp-c × cron", "Issue": "100% Approval Rate on cron — likely pre-auth captures, not real approvals", "Fix": "Flagged as data artifact; excluded from cron Approval Rate baseline"},
    ])
    st.dataframe(dq_df, width="stretch", hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PRODUCT STORY
# ══════════════════════════════════════════════════════════════════════════════
with tab_product:
    st.header("Product Story — v1 Narrative")

    # ── WHO IS THE OPERATOR ──────────────────────────────────────────────────
    st.markdown("### Who is the operator?")
    st.markdown("""
The primary user is the **Payments Operations Lead** — the person at Aplazo who owns collection performance.
They are not an engineer. They understand PSP contracts, approval rate trends, and cost targets, but they cannot
deploy code and should not have to.

**The problem today:** everything is reactive. Approval Rate drops on a Monday morning report. The ops lead files a ticket
to engineering. Two weeks later, a fix ships. In the meantime, every transaction that could have gone to a
better PSP is going to the wrong one, and nobody knows how much it costs.

**What changes with the orchestrator:** the ops lead becomes proactive. They see issues in the dashboard before
the Monday report. They can respond to a PSP outage or a new pricing deal in minutes, without touching code,
without waiting for engineering. The system does not take their job — it gives them their job back.
""")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Without the Orchestrator**")
        without_df = pd.DataFrame([
            {"Scenario": "PSP-C goes down at 2am", "What happens": "On-call engineer wakes up, edits env vars, redeploys. ~45 min of misrouted traffic"},
            {"Scenario": "New PSP pricing deal closes", "What happens": "PM files ticket → sprint planning → 2-week delay before routing reflects new economics"},
            {"Scenario": "Bancoppel Approval Rate drops this week", "What happens": "Analyst notices in weekly SQL report, files ticket, fix ships next sprint"},
            {"Scenario": "Cron batch over-retrying dead cards", "What happens": "Invisible until monthly cost report — no one is watching retry waste in real time"},
        ])
        st.dataframe(without_df, width="stretch", hide_index=True)

    with col2:
        st.markdown("**With the Orchestrator**")
        with_df = pd.DataFrame([
            {"Scenario": "PSP-C goes down at 2am", "What happens": "Operator raises volume guardrail — traffic shifts to psp-e/psp-o automatically. Recovery: < 2 min, no code"},
            {"Scenario": "New PSP pricing deal closes", "What happens": "Ops lead updates fee config. Engine rescores every future transaction immediately"},
            {"Scenario": "Bancoppel Approval Rate drops this week", "What happens": "Issuer Approval Rate alert fires. Operator sees it, adjusts Bancoppel routing preference in the UI"},
            {"Scenario": "Cron batch over-retrying dead cards", "What happens": "Hard decline interceptor stops it automatically. Dashboard shows exactly how much fee waste was avoided"},
        ])
        st.dataframe(with_df, width="stretch", hide_index=True)

    # ── CONFIGURATION MODEL ──────────────────────────────────────────────────
    st.markdown("### Configuration Model")
    st.markdown("""
<div class="callout-blue">
<b>Why rules-based and not ML?</b><br><br>
The honest answer is: we do not have the data ML needs yet. To train a model that predicts
"what would psp-e's approval rate be for <i>this specific transaction</i> if we routed it there?",
we need split routing experiments — where we deliberately sent the same type of transaction to
different PSPs and observed both outcomes. That counterfactual data does not exist in the March dataset.
What we have is observational: we only know the outcome of the PSP that was actually used.<br><br>
Beyond the data constraint, rules earn trust first. If the orchestrator makes a wrong decision at 2am,
the ops team needs to be able to read the logic and understand why. A rules-based system is fully
transparent — every decision traces back to a formula and a data observation. ML is explicitly on
the v2 roadmap, after A/B routing experiments generate the counterfactual data needed to train it properly.
</div>""", unsafe_allow_html=True)

    st.markdown("""
The system has two types of inputs: **fixed rules** (informed by data, not negotiable) and
**operator dials** (business levers that change based on context):
""")

    col_fixed, col_dial = st.columns(2)
    with col_fixed:
        st.markdown("**Fixed rules — grounded in data**")
        st.markdown("""
- **Hard decline short-circuit:** If the error is "insufficient funds" or "stolen card," stop — no retry, no PSP switch.
  *Why:* These errors are permanent. Retrying them doesn't change the outcome, it just costs a transaction fee per attempt.
  The data showed ~771K terminal failures per month that hit this pattern.

- **Cron batch cap at 3 attempts:** Automated overnight runs stop at 3 tries instead of 5.
  *Why:* There is no user present to resolve a soft decline — no one to top up their account or call their bank.
  The data shows cron Approval Rate at 30.4% vs. 78.8% for user-present. Attempts 4 and 5 in batch are mostly waste.

- **psp-e excluded from cron batch:** psp-e is never used for overnight batch transactions.
  *Why:* psp-e collapses to 29–35% Approval Rate on batch. The data is unambiguous. This is not a judgment call.
""")
    with col_dial:
        st.markdown("**Operator dials — adjustable without code**")
        st.markdown("""
- **Optimization Knob (0.0 → 1.0):** Slides the scoring weight between cost minimization and approval rate maximization.
  *When to change:* Slide toward 1.0 at end-of-month when collections pressure is high. Slide toward 0.0 during
  margin review weeks. Default 0.5 is the balanced mode.

- **Volume Guardrail (0–30%):** Minimum traffic floor per secondary PSP.
  *Why it exists:* Without a floor, the engine routes almost everything to psp-c (the best PSP). That creates
  single-point-of-failure risk. Secondary PSPs also degrade when they see low volume — their systems
  get cold, their teams deprioritize the relationship. The 10% default keeps them warm for failover.

- **PSP fee table:** Updated by Finance when a new contract is signed.
  *Effect:* The scoring formula recalculates immediately. No code deploy needed.
""")

    # ── FEATURE LIST ─────────────────────────────────────────────────────────
    st.markdown("### ✅ What was built — feature list")
    features_df = pd.DataFrame([
        {"#": "F1",  "Feature": "Data cleaning — normalize case, strip whitespace, handle nulls",            "File": "step1_baseline.py",    "Status": "✓ Done"},
        {"#": "F2",  "Feature": "Approval rate at attempt-level AND installment-level",                      "File": "step1_baseline.py",    "Status": "✓ Done"},
        {"#": "F3",  "Feature": "Approval rate cuts: by PSP, gateway, issuer, amount tier, hour",            "File": "step1_baseline.py",    "Status": "✓ Done"},
        {"#": "F4",  "Feature": "Retry analysis: approval rate per attempt # + error recovery rates",        "File": "step1_baseline.py",    "Status": "✓ Done"},
        {"#": "F5",  "Feature": "Credit vs. debit split per PSP using BIN join",                            "File": "step1b_deep_dive.py",  "Status": "✓ Done"},
        {"#": "F6",  "Feature": "Volume concentration analysis across PSPs",                                 "File": "step1b_deep_dive.py",  "Status": "✓ Done"},
        {"#": "F7",  "Feature": "Issuer × PSP approval rate matrix (top Mexican issuers)",                  "File": "step1b_deep_dive.py",  "Status": "✓ Done"},
        {"#": "F8",  "Feature": "PSP-switch-on-retry analysis",                                             "File": "step1b_deep_dive.py",  "Status": "✓ Done"},
        {"#": "F9",  "Feature": "Hard decline detection — 12 error patterns, immediate stop",               "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F10", "Feature": "Retry cap policy per channel (cron/normal) and issuer risk tier",          "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F11", "Feature": "Issuer-aware PSP scoring with configurable knob (0.0–1.0)",                "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F12", "Feature": "Cron channel override — psp-e excluded from batch routing",                "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F13", "Feature": "Volume guardrail — minimum traffic share per secondary PSP",               "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F14", "Feature": "Full routing decision object with reasoning fields",                        "File": "orchestrator.py",      "Status": "✓ Done"},
        {"#": "F15", "Feature": "Interactive web UI — live transaction simulation + explainability",         "File": "app.py",               "Status": "✓ Done"},
        {"#": "F16", "Feature": "PSP fee reference and issuer approval rate matrix in UI",                  "File": "app.py",               "Status": "✓ Done"},
    ])
    st.dataframe(features_df, width="stretch", hide_index=True)

    # ── WHAT V1 IS MISSING ───────────────────────────────────────────────────
    st.markdown("### 🚫 What v1 intentionally does NOT do — and why")
    st.markdown('<p style="color:#6b7280;font-size:0.9rem">These are not oversights. Each is a deliberate decision. If the panel asks "why didn\'t you build X" — the answer is here.</p>', unsafe_allow_html=True)

    st.markdown("""
<div style="border:1px solid #fecaca;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">❌ No machine learning model</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#dc2626">Why it's out:</span> ML needs examples where the same transaction was sent to different PSPs and you saw both outcomes — called counterfactual data. The March dataset is purely observational: we only know what happened on the PSP that was actually used. Training ML on that teaches it "psp-c always wins" because psp-c always got the good transactions. That's a circular loop, not intelligence.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">What unlocks it:</span> 6 months of A/B routing experiments — send 10% of traffic to random PSP assignment and observe both outcomes. That generates the counterfactual labels ML needs.</div>
  <div style="font-size:0.85rem;color:#2563eb;font-weight:600">→ Roadmap: v3 — after A/B data is collected</div>
</div>

<div style="border:1px solid #fecaca;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">❌ No issuer routing for 62% of transactions (psp-o and psp-d)</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#dc2626">Why it's out:</span> psp-o and psp-d do not log BIN numbers in their event data. Without a BIN we cannot identify the card's bank. Without the bank we cannot apply the issuer × PSP matrix. Those transactions route generically — same as today's static system. Not a regression, just a ceiling we can't break without a data pipeline fix on their side.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">What unlocks it:</span> Ask psp-o and psp-d to include BIN in their webhook payloads. One-time infrastructure fix. Highest ROI change available — every day without it, 62% of volume routes blind.</div>
  <div style="font-size:0.85rem;color:#2563eb;font-weight:600">→ Roadmap: v2 priority #1</div>
</div>

<div style="border:1px solid #fecaca;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">❌ No SPEI / WhatsApp fallback channel</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#dc2626">Why it's out:</span> v1 scope is card transactions only. SPEI is a bank transfer — different payment rail, different API, different reconciliation. Scoping it in would have split engineering focus and delayed shipping the card routing. But the data justifies it: admin-dashboard runs at 8.2% approval because agents retry dead cards. After 2 failures, the card is the wrong instrument.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">What unlocks it:</span> After 2 agent-dashboard card failures, automatically send a SPEI payment link via WhatsApp. Bypasses the card balance entirely — reaches a different funding source. No PSP routing changes needed.</div>
  <div style="font-size:0.85rem;color:#2563eb;font-weight:600">→ Roadmap: v1.5 — first feature after v1 stabilizes</div>
</div>

<div style="border:1px solid #fecaca;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">❌ No real-time approval rate updates</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#dc2626">Why it's out:</span> The issuer × PSP matrix refreshes monthly from the analysis scripts. A PSP degrading on Tuesday won't be reflected until next month. Building a real-time pipeline — streaming event processing, a metrics store, hourly recalculation — adds weeks of infrastructure before we've even validated the routing logic. The Δ Margin alert catches degradation within 4 hours, which is good enough for v1.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">What unlocks it:</span> A production metrics store connected to the live event stream. The analysis logic already exists — it just needs to run hourly instead of monthly.</div>
  <div style="font-size:0.85rem;color:#2563eb;font-weight:600">→ Roadmap: v1.5</div>
</div>

<div style="border:1px solid #fecaca;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">❌ No customer-level memory across installments</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#dc2626">Why it's out:</span> The orchestrator sees each transaction in isolation. It doesn't know this is the same customer's 3rd failed installment in a row, or that they have 4 more due. That context is in loans_data — we analyzed it but didn't wire it into v1 routing. Joining two data sources at request time adds latency and complexity before the base routing is even proven.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">What unlocks it:</span> A lightweight customer reliability score built from payment history. All the data is already in the pipeline. This upgrades the orchestrator from transaction-level to customer-level intelligence.</div>
  <div style="font-size:0.85rem;color:#2563eb;font-weight:600">→ Roadmap: v2</div>
</div>
""", unsafe_allow_html=True)

    # ── ROADMAP ──────────────────────────────────────────────────────────────
    st.markdown("### 🗺️ The full roadmap")
    roadmap2_df = pd.DataFrame([
        {"Version": "v1 — now", "What ships": "Rules-based routing · Hard decline stop · Knob · Guardrail · Cron rules", "Why this order": "Establishes baseline, earns operator trust, stops the most obvious waste immediately"},
        {"Version": "v1.5",     "What ships": "Hourly approval rate refresh · SPEI/WhatsApp fallback · Real-time Δ Margin alert", "Why this order": "Closes detection gap and adds highest-ROI channel switch without touching routing core"},
        {"Version": "v2",       "What ships": "BIN logging fix on psp-o/psp-d · A/B routing experiment framework · Customer reliability score", "Why this order": "BIN fix unlocks issuer routing for 62% of volume — single biggest quality jump available"},
        {"Version": "v3",       "What ships": "ML-based PSP scoring · Multi-method orchestration (card + SPEI + OXXO) · Continuous learning", "Why this order": "ML only makes sense after A/B data exists and rules have proven which signals matter"},
    ])
    st.dataframe(roadmap2_df, width="stretch", hide_index=True)

    # ── GUARDRAILS & FAILURE MODES ───────────────────────────────────────────
    st.markdown("### ⚠️ Guardrails & Failure Modes")
    st.markdown('<p style="color:#6b7280;font-size:0.9rem">Every system can make things worse. Being honest about when and why is what separates a v1 worth shipping from one that isn\'t.</p>', unsafe_allow_html=True)

    st.markdown("""
<div style="border:1px solid #fed7aa;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">⚠️ Stale approval rate matrix — silent PSP degradation</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#b45309">Scenario:</span> psp-c starts having a technical issue today and its approval rate drops from 73% to 40%. The orchestrator still routes to psp-c as primary because last month's matrix says 73%.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#1d4ed8">How to detect:</span> Hourly alert fires if any PSP's observed approval rate drops more than 10 points below its matrix value. The ops lead investigates within the hour.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">How to recover:</span> Operator overrides the routing rule in the UI. Matrix auto-corrects on next refresh. No code deploy.</div>
  <div style="font-size:0.85rem;color:#6b7280">Longer-term fix: v1.5 real-time matrix refresh closes this gap from weeks to hours.</div>
</div>

<div style="border:1px solid #fed7aa;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">⚠️ BIN table gaps — new issuers get no intelligence</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#b45309">Scenario:</span> A new Mexican neobank launches and its cards start appearing in transactions. The BIN isn't in our reference file. The orchestrator can't identify the issuer and can't apply the matrix.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#1d4ed8">How to detect:</span> Monitor the rate of "unknown issuer" routing in logs. If it climbs, a new issuer is entering volume.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">How to recover:</span> Falls back to psp-c by default — never worse than today's static routing. The floor is the baseline.</div>
  <div style="font-size:0.85rem;color:#6b7280">Longer-term fix: Monthly BIN table refresh from card network data feeds.</div>
</div>

<div style="border:1px solid #fed7aa;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">⚠️ Concentration risk — psp-c dependency</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#b45309">Scenario:</span> Knob at 1.0, guardrail at 5%. Engine routes 95% of traffic to psp-c. psp-c has an outage. 95% of transactions have nowhere to go.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#1d4ed8">How to detect:</span> Concentration alert fires if any single PSP exceeds 90% of hourly volume.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">How to recover:</span> Operator raises the guardrail slider. Engine redistributes across the next incoming transactions. 5-second fix.</div>
  <div style="font-size:0.85rem;color:#6b7280">Prevention: The 10% default guardrail makes this the non-default case.</div>
</div>

<div style="border:1px solid #fed7aa;border-radius:10px;padding:18px 20px;margin-bottom:12px">
  <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px">⚠️ psp-c × cron 100% approval rate — suspicious data artifact</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#b45309">Scenario:</span> The data shows psp-c with 100% approval rate on cron batch. Real payment collections don't work that way. Hypothesis: these are pre-authorization captures being logged as approvals, not new charges.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#1d4ed8">How to detect:</span> Audit psp-c cron event types with engineering — compare capture events vs. new collection events.</div>
  <div style="margin-bottom:6px"><span style="font-weight:600;color:#16a34a">How to recover:</span> Separate capture events from collection events in the pipeline. Recalculate psp-c cron approval rate on collection events only.</div>
  <div style="font-size:0.85rem;color:#6b7280">Note: Current cron routing still works correctly — the artifact only affects how we report psp-c's cron performance, not the routing decision itself. Flagged proactively.</div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — OBSERVABILITY
# ══════════════════════════════════════════════════════════════════════════════
with tab_obs:
    st.header("Observability Surface")
    st.caption("What the operator sees, monitors, and acts on every day.")

    st.markdown("### The North Star Metric")
    st.markdown("""
<div class="formula-box">
<span class="highlight">Δ Margin</span> = Revenue_collected(Orchestrator) − Revenue_collected(Static_baseline)
<br><br>
<span class="comment">Measured on a rolling 4-hour window. If Δ Margin &lt; 0, the orchestrator is underperforming
the naive baseline. Auto-fallback to static routing activates and an alert fires.</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("### Core Alert Framework")
    alerts_df = pd.DataFrame([
        {"Alert": "🔴 Degradation trigger", "Condition": "Δ Margin < 0 on 4-hour rolling window", "Action": "Auto-revert to static routing; page on-call"},
        {"Alert": "🟡 Approval Rate anomaly by issuer", "Condition": "Observed Approval Rate for any issuer deviates >10pp from matrix value", "Action": "Flag for matrix refresh; operator reviews routing rule"},
        {"Alert": "🟡 Concentration breach", "Condition": "Any single PSP receives >90% of hourly volume", "Action": "Operator raises guardrail; auto-rebalances next transaction"},
        {"Alert": "🟡 Hard decline surge", "Condition": ">30% of attempts in any hour are hard declines", "Action": "Investigate upstream fraud pattern or card expiry wave"},
        {"Alert": "🔵 Retry waste tracker", "Condition": "Daily report: attempts with 0% expected recovery (hard declines retried)", "Action": "Quantifies cost saved by intercept rule; confirms it's working"},
        {"Alert": "🔵 cron collection rate", "Condition": "Daily: installment-level Approval Rate for cron vs. prior 7-day average", "Action": "Detects if cron retry cap is set too aggressively"},
    ])
    st.dataframe(alerts_df, width="stretch", hide_index=True)

    st.markdown("### Daily Operator Dashboard (what they look at)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Installment-level Approval Rate", "82.5%", "+0.0pp vs static baseline", help="The true collection rate — installments with at least one approval")
    m2.metric("Hard declines stopped", "~771K/mo", "0% recovery → $0 wasted", help="Attempts the interceptor blocked from retrying")
    m3.metric("psp-c share of volume", "~19%", "↑ from static 0% intelligent routing", help="Should stay below 90% due to guardrail")
    m4.metric("Δ Margin vs baseline", "+est. $X MXN", "TBD after A/B test", help="Requires A/B experiment to quantify lift precisely")

    st.markdown("### v2 / v3 Roadmap")
    roadmap_df = pd.DataFrame([
        {"Version": "v1 (now)", "Capability": "Rules-based routing + hard decline intercept + knob + guardrail", "Key unlock": "Eliminate retry waste; shift volume from psp-o to psp-c"},
        {"Version": "v1.5", "Capability": "Hourly Approval Rate matrix refresh from production metrics", "Key unlock": "Catch PSP degradation within hours, not monthly"},
        {"Version": "v2", "Capability": "BIN logging added to psp-o and psp-d event pipelines", "Key unlock": "Issuer routing for 100% of volume, not just 21%"},
        {"Version": "v2", "Capability": "SPEI/WhatsApp fallback trigger on admin-dashboard failures", "Key unlock": "Convert the 91.8% failure rate on agent retries to alternative channel"},
        {"Version": "v2", "Capability": "A/B split routing experiment framework", "Key unlock": "Measure true Δ Margin lift from orchestrator vs. static baseline"},
        {"Version": "v3", "Capability": "ML-based PSP scoring model (gradient boosted)", "Key unlock": "Capture non-linear feature interactions; continuous learning from outcomes"},
        {"Version": "v3", "Capability": "Multi-method orchestration (card + SPEI + OXXO)", "Key unlock": "Optimal channel selection, not just PSP selection"},
    ])
    st.dataframe(roadmap_df, width="stretch", hide_index=True)

    st.markdown("### Open Questions for the Panel")
    st.markdown("""
<div class="callout-amber">
These are the data gaps I found that Aplazo engineering needs to answer before a production rollout:
<ol>
<li><b>Why do psp-o and psp-d not log BIN numbers?</b> — Fixing this is the single highest-leverage data pipeline change. It unlocks issuer routing for 62% of current volume.</li>
<li><b>What exactly are the psp-c × cron 100% Approval Rate transactions?</b> — If they're pre-auth captures, psp-c's cron Approval Rate is artificially inflated and cron routing logic needs adjustment.</li>
<li><b>Are there contractual volume minimums per PSP?</b> — If Aplazo has committed to X% of volume per PSP by contract, the guardrail must encode those commitments, not just risk preferences.</li>
<li><b>Does any PSP charge a per-attempt decline fee?</b> — The brief says "—" for decline fees on all PSPs, but this changes the retry math significantly if any PSP does charge on declines.</li>
</ol>
</div>""", unsafe_allow_html=True)
