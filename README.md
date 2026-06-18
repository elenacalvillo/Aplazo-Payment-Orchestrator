# Aplazo Payment Orchestrator — V1 Prototype

**Candidate:** Elena Calvillo  
**Dataset:** `payment_events-march2026.csv` · `bins_data.csv` · `loans_data-march2026.csv`  
**Scope:** Card transactions only · March 2026 · 5.9M events

---

## What Was Built

A data-driven payment routing engine that decides which PSP to use — and when to stop trying — for every loan installment collection attempt. Includes a fully interactive Streamlit app for live demo and operator use.

---

## Project Structure

| File | Purpose |
|------|---------|
| `orchestrator.py` | Core routing engine — the `PaymentOrchestrator` class with all decision logic |
| `app.py` | Interactive Streamlit Control Plane — Simulator, Formula, Data Findings, Product Story, Observability |
| `product_spec.html` | Complete product specification + panel defense guide (open in any browser, no server needed) |
| `analysis_summary.md` | Data analysis notes — key findings, methodology, blind spots |
| `step1_baseline.py` | Step 1 analysis script — baseline approval rate cuts by PSP, gateway, issuer, amount tier, hour |
| `step1b_deep_dive.py` | Step 1b deep dive — credit/debit split, issuer × PSP matrix, retry pattern analysis |

---

## How to Run

### Requirements

```bash
pip install streamlit pandas numpy matplotlib
```

### Launch the interactive app

```bash
cd <project-folder>
streamlit run app.py
```

Opens at `http://localhost:8501` — no API keys, no database, no external dependencies.

### Run the analysis scripts (optional)

Requires the original CSV files in the same directory:

```bash
python3 step1_baseline.py      # baseline approval rate cuts
python3 step1b_deep_dive.py    # deep-dive: issuer × PSP matrix, retry analysis
```

### View the product spec

Open `product_spec.html` directly in any browser — no server needed.

---

## Simulator Quick Start

1. Open the app at `http://localhost:8501`
2. In the left sidebar, set the **Optimization Knob** (0 = minimize cost, 1 = maximize approval rate)
3. Set the **Volume Guardrail** (minimum traffic floor per secondary PSP, default 10%)
4. In the Simulator tab, fill in: transaction amount, card issuer, collection gateway, attempt number, and last error (if retry)
5. Click **Route Transaction** to see the full decision with scoring math and visual flow

---

## Key Design Decisions

- **Rules-based v1, not ML** — the issuer × PSP matrix already captures most approval rate variance; ML requires counterfactual data from A/B routing experiments that don't exist yet
- **Hard decline short-circuit** — permanently failed cards (insufficient funds, fraud) are stopped immediately, not retried, to avoid unnecessary fee spend
- **Cron batch cap at 3 attempts** — overnight batch runs have zero user-present recovery potential; the data shows marginal approval rate gains beyond attempt 3
- **10% volume guardrail** — prevents concentration risk and keeps secondary PSPs warm for failover
- **BIN-aware routing** — psp-c and psp-e log BIN data; psp-o and psp-d do not — this asymmetry is explicitly modeled in the routing logic
