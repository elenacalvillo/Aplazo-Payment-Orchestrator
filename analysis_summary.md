# Aplazo Payment Orchestrator — Data Analysis Notes

**Candidate:** Elena Calvillo  
**Dataset:** 5.9M payment events · March 2026  
**Scripts:** `step1_baseline.py`, `step1b_deep_dive.py`

---

## Methodology

All analysis was performed on `payment_events-march2026.csv` joined against `bins_data.csv` for BIN-level issuer and funding type enrichment. Terminal events only (status = `complete` or `failed`) were used for approval rate calculations to avoid counting in-progress attempts. Two approval rate definitions were tracked throughout:

- **Attempt-level AR**: approvals ÷ terminal attempts → **26.25%**
- **Installment-level AR**: installments with ≥1 approval ÷ total installments → **82.51%**

The gap between these two numbers is the central story: the system eventually collects most installments, but it takes an average of 3+ attempts to get there. The orchestrator's job is to collapse that gap by getting the routing right on attempt #1.

---

## Finding 1 — PSP Performance Is Wildly Unequal

| PSP | Approval Rate | Fee | Traffic Share |
|-----|--------------|-----|---------------|
| psp-c | 73.4% | 1.55% | 18.8% |
| psp-e | 55.8% | 1.68% | 19.2% |
| psp-o | 49.8% | 1.58% | 54.8% |
| psp-d | 33.0% | 1.69% | 7.2% |

**Key insight:** psp-c is simultaneously the cheapest and the highest-performing PSP. psp-o receives 54.8% of all traffic by default but approves less than half of transactions. This is not a performance problem — it's a routing problem. The legacy static routing is sending the majority of volume to the wrong provider.

---

## Finding 2 — The Retry Cascade Myth

Analyzed over 500,000 retry events to test whether switching PSP on retry improves outcomes.

| Retry behavior | Attempts | Approval Rate |
|---------------|---------|--------------|
| Same PSP | ~420K | 50.6% |
| Switched PSP | ~82K | 50.5% |

**Conclusion:** PSP-switching on retry provides statistically zero lift (0.1pp difference). Value is won or lost on getting the routing right on attempt #1. This finding directly motivates the orchestrator's primary design principle: smart first-attempt routing, not cascade optimization.

---

## Finding 3 — Issuer × PSP Interaction Is the Biggest Signal

Different card issuers perform dramatically differently across PSPs:

| Issuer | psp-c AR | psp-e AR | Delta |
|--------|---------|---------|-------|
| Nu MX | 81.2% | 15.8% | −65pp |
| Banco Mercantil del Norte | 60.7% | 68.5% | +7.8pp |
| Bancoppel | 80.9% | — | — |
| BBVA | 72.1% | — | — |

**Key insight:** Nu MX cards should never touch psp-e. Banco Mercantil cards should be routed to psp-e when psp-c is unavailable. This issuer-level intelligence is only possible because psp-c and psp-e log BIN data — psp-o and psp-d do not, creating a critical data gap for 62% of transaction volume.

---

## Finding 4 — Cron Batch Is a Distinct Problem

47% of all transaction volume runs via automated overnight batch (`cron`/`batch` collection gateways). Cron batch approval rate is **30.4%** vs. **78.8%** for user-present transactions. This is not a PSP problem — there is no user available to resolve soft declines (expired cards, insufficient funds) in real time. The appropriate response is a stricter retry cap (3 attempts max) and a channel switch recommendation (WhatsApp/SPEI) after failures, not more PSP retries.

---

## Finding 5 — Admin Dashboard Has a Behavioral Problem, Not a PSP Problem

The `admin-dashboard-nextpayment` gateway shows only **8.2% approval rate**. Top error: "insufficient funds" (recurring). Agents are manually retrying cards belonging to customers who are already 2–3 installments behind — the card is not the right channel for these customers. Recommendation: after 2 agent-dashboard failures on the same card, trigger a SPEI/WhatsApp payment link. This is a v1.5 product change, not a routing fix.

---

## Data Gaps Identified

1. **psp-o and psp-d do not log BIN numbers** — issuer-level routing is impossible for 62% of volume until this pipeline gap is closed. Highest-leverage infrastructure fix available.
2. **No counterfactual routing data** — all analysis is observational. True lift from the orchestrator cannot be measured without an A/B split routing experiment.
3. **March data only** — Semana Santa falls in March/April, which may inflate cron batch failure rates. One month is insufficient to establish reliable seasonal baselines.
4. **loans_data unused** — installment-level data (which customers are behind, how many installments remain) was not incorporated into routing decisions in v1. This is a significant untapped signal for collection prioritization.

---

## V1 Engine Rules Implemented

| Rule | Trigger | Action |
|------|---------|--------|
| Hard decline short-circuit | Error matches permanent failure pattern (insufficient funds, fraud, stolen card) | Stop immediately, no retry |
| Cron batch cap | `collection_gateway` contains cron/batch/auto | Max 3 attempts instead of 5 |
| Issuer-aware routing | BIN match available + transaction on psp-c or psp-e | Route to highest AR PSP for that issuer |
| psp-e cron exclusion | Cron transaction | Exclude psp-e (collapses to 29–35% AR on batch) |
| Volume guardrail | Secondary PSP allocation | Maintain ≥10% traffic floor per secondary PSP |
| Knob-weighted scoring | All transactions | Score = (knob × AR_score) + (1−knob × cost_efficiency_score) |
