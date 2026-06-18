# Aplazo Payment Orchestrator — V1 Prototype

**Candidate:** Elena Calvillo  
**Company:** Aplazo (BNPL, Mexico)  
**Dataset:** 5.9M payment events · March 2026  
**Scope:** Card transactions only · Prototype

---

## One Sentence

Aplazo collects loan payments from customers' cards. This orchestrator automatically picks the best payment processor for each transaction to maximize the chance of success while minimizing fees — with no code deploy required to change routing behavior.

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Payment processors (PSPs) | 4 |
| Installments eventually collected | 82.5% |
| First-attempt approval rate | 26.3% |
| Transactions run via overnight batch | 47% |
| Hard declines intercepted (zero recovery) | ~771K / month |

---

## The Problem

### What is Aplazo?

Aplazo is a **Buy Now, Pay Later (BNPL)** platform in Mexico. A customer buys something at a store — say, a $3,000 MXN phone — and instead of paying the full amount, they pay in installments: maybe 6 payments of $500 MXN each, once a month. Aplazo pays the merchant upfront and then collects those installments from the customer's debit or credit card automatically.

### What is a PSP?

To charge a customer's card, Aplazo works through **Payment Service Providers (PSPs)** — intermediary companies that handle the technical connection to the banking network. Think of them like shipping carriers: they all deliver the same package (the charge), but with different prices and reliability depending on the destination (the bank).

### The actual problem: static routing

Before this project, Aplazo's system had **no intelligence about which PSP to use**. Every transaction went to the same PSP by default — regardless of which bank issued the card, whether it was a batch run or user-initiated, whether the error guaranteed failure, or how many retries had already happened.

The consequence: Aplazo was sending ~55% of all traffic to psp-o (49.8% approval rate) while psp-c (73.4% approval rate, cheaper fee) was underutilized. Money was being left on the table on every billing cycle.

---

## PSP Profiles

### psp-c — The Workhorse
**Primary PSP · Best in class on every metric**

| Approval Rate | Fee | BIN data | Current traffic |
|--------------|-----|----------|----------------|
| 73.4% | 1.55% (cheapest) | ✅ Yes | 18.8% |

The standout performer: cheapest AND best approval rate. Logs BIN data alongside psp-e, enabling issuer-level routing intelligence. Strong across all Mexican issuers — Nu MX approves at 81.2%, Bancoppel at 80.9%, Uala at 84.8%. Default first choice for cron batch and high-value tickets.

### psp-e — The Specialist
**Secondary PSP · Use only when issuer data says so**

| Approval Rate | Fee | BIN data | Current traffic |
|--------------|-----|----------|----------------|
| 55.8% | 1.68% | ✅ Yes | 19.2% |

Higher fee and lower average approval rate than psp-c — but it **wins for specific issuers**. Banco Mercantil del Norte approves at 68.5% on psp-e vs. 60.7% on psp-c (+7.8pp). Key weakness: collapses on credit cards (29.9%) and cron batch (29–35%). Never the default — only when the issuer matrix says it wins. Exclude entirely from overnight batch runs.

### psp-o — The Overused Fallback
**Generic fallback · Currently over-allocated**

| Approval Rate | Fee | BIN data | Current traffic |
|--------------|-----|----------|----------------|
| 49.8% | 1.58% | ❌ No | 54.8% |

The biggest opportunity in the data. Processes **54.8% of all card volume** but approves less than half of transactions — while psp-c (cheaper, better) handles only 18.8%. Critical data gap: psp-o does not log BIN numbers, so issuer-level routing is impossible through it. Its role is strictly a volume backstop, never a first choice.

### psp-d — The Last Resort
**Worst performer · Last-resort fallback only**

| Approval Rate | Fee | BIN data | Current traffic |
|--------------|-----|----------|----------------|
| 33.0% | 1.69% (most expensive) | ❌ No | 7.2% |

The worst combination: lowest approval rate AND highest fee. Also no BIN logging. Exists in the orchestrator only as a last-resort fallback when all other PSPs are unavailable or over the guardrail cap. Should receive only the minimum guardrail floor to keep the connection alive.

---

## Data & Findings

### The 3 data sources

| File | Rows | What it contains | Used for |
|------|------|-----------------|----------|
| `payment_events-march2026.csv` | 5.9M | Every payment attempt: card, PSP, outcome, error, amount | All approval rate calculations, retry analysis |
| `loans_data-march2026.csv` | 1.1M | Loan metadata: total amount, installments, merchant, status | Installment-level context |
| `bins_data.csv` | 1,282 | Maps card BIN numbers to issuing bank, card type, brand | Knowing which bank issued the card for routing |

A **BIN** is the first 6–8 digits of a card number — they publicly identify which bank issued it. Only 21.3% of card rows matched a BIN entry.

---

### Finding 1 — The most important PSP is the one Aplazo uses the least

psp-c has the best approval rate (73.4%) and the lowest fee (1.55%) — it wins on every dimension. But legacy routing sends only 18.8% of traffic there and dumps 54.8% on psp-o, which approves less than half of transactions (49.8%).

> **In plain terms:** Imagine you have four checkout lanes at a supermarket. Lane C is the fastest and cheapest. The current system sends most customers to Lane O, which is slow and expensive. Nobody decided this — it's just how the static rules were written. The orchestrator fixes the default.

**So we built:** A scoring engine that routes to psp-c first by default, and only uses psp-o and psp-d as fallbacks — not as primary lanes.

---

### Finding 2 — The bank that issued the card matters more than the PSP you choose

The same card issuer can get completely different results depending on which PSP processes it:

| Issuer | psp-c AR | psp-e AR | Delta |
|--------|---------|---------|-------|
| Nu MX | 81.2% | 15.8% | −65pp |
| Banco Mercantil del Norte | 60.7% | 68.5% | +7.8pp |
| Bancoppel | 80.9% | — | — |
| BBVA | 72.1% | — | — |
| Uala | 84.8% | — | — |

> **In plain terms:** It's like knowing that Airline A is great for domestic flights but always delays internationals, while Airline B is the opposite. The right choice depends on your destination — not just which airline is "better overall." The card's bank is the destination.

**So we built:** An issuer × PSP matrix. For every transaction where we know the card's bank, we route to the PSP with the highest historical approval rate for that specific bank — not the highest average overall.

---

### Finding 3 — Overnight batch payments are a completely different problem

47% of all transactions run automatically at night ("cron batch"). Their approval rate is **30.4%** — vs. **78.8%** when a user is actively at checkout. psp-e is especially bad on cron: 29–35% approval rate.

> **In plain terms:** When a customer is at checkout, they can fix problems in real time — change cards, top up their account, call their bank. At 3am when the batch runs, nobody is watching. Retrying 5 times at 3am on a card that drained at midnight is pure waste.

**So we built:** A separate rule set for cron transactions — max 3 attempts instead of 5, psp-e excluded entirely. Cron and checkout are not the same product.

---

### Finding 4 — Switching payment processor on retry does absolutely nothing

Analyzed over 500,000 retry attempts:

| Retry behavior | Attempts | Approval Rate |
|---------------|---------|--------------|
| Same PSP | ~420K | 50.6% |
| Switched PSP | ~82K | 50.5% |

The difference is 0.1 percentage points — statistically zero.

> **In plain terms:** The whole industry assumes "if PSP A fails, try PSP B." The data says that's wrong. Whether a payment succeeds on retry depends on the *type of error*, not which company processes the retry. A declined card is a declined card.

**So we built:** A system focused entirely on getting the first routing decision right, not on building smarter cascade logic. Retry is a safety net, not a strategy.

---

### Finding 5 — Nearly a million failures per month have zero chance of ever succeeding

**771,000 transactions** per month fail with "insufficient funds" and show **0% recovery rate** on the next attempt. The system was retrying them anyway — paying a transaction fee each time.

> **In plain terms:** If someone's bank account is empty, trying to charge the card again in the next hour will not fill the account. Every retry costs Aplazo a fee. We were paying to confirm what we already knew.

**So we built:** A hard stop list. If the error message signals a permanent problem — empty account, stolen card, fraud flag — the orchestrator stops immediately and does not try again. This is the single highest-ROI rule in the entire system.

---

### Finding 6 — Manual agent retries are a behavioral problem, not a routing problem

The `admin-dashboard` channel — where Aplazo agents manually trigger payment retries — has only **8.2% approval rate**. The top error is "insufficient funds" — repeated, over and over. Agents are retrying cards belonging to customers who are already 2–3 installments behind. No PSP will approve it. The problem is not which processor the agent uses — the card is the wrong payment channel for this customer at this moment.

**So we built (v1):** The hard decline interceptor also covers agent retries — it stops the loop.  
**What's coming (v1.5):** After 2 agent-dashboard failures on the same card, automatically send the customer a SPEI payment link via WhatsApp. That reaches a different funding source entirely and breaks the dead-card loop.

---

## The Engine

### How a payment flows through the orchestrator

```
Installment due → Transaction payload → Orchestrator scores PSPs → Route to best PSP
                                              ↓
                                        Declined?
                                              ↓
                              Hard decline (no funds / fraud) → STOP. No retry.
                              Soft decline (timeout / unavailable) → Retry up to cap
```

The orchestrator takes one transaction as input and returns one decision as output. It runs three checks in sequence:

1. **Hard Decline Check** — Is the error one that will never recover? (insufficient funds, fraud detected, card expired) → Stop immediately, no fee wasted.
2. **Retry Cap Check** — Has this installment been attempted too many times? Normal: max 5. Cron: max 3.
3. **PSP Scoring** — Score every PSP using a weighted blend of cost efficiency and issuer-specific approval rate. The blend ratio is controlled by The Knob.

### The Knob — the core control parameter

A single number between **0.0 and 1.0** that controls what the orchestrator optimizes for:

```
0.0 ─────────────── 0.5 ─────────────── 1.0
Min Cost           Balanced           Max Acceptance
(cheapest PSP)  (recommended)    (best AR by issuer)
```

**Score = (knob × AR_score) + (1 − knob × cost_efficiency_score)**

**Live example — Banco Mercantil del Norte, $870 MXN:**
- knob = **1.0** → **psp-e** (68.5% AR, fee $14.62 MXN)
- knob = **0.0** → **psp-c** (60.7% AR, fee $13.48 MXN)

The knob lets the operator respond to business context without touching code. End-of-month pressure on collections? Slide toward 1. Margin review week? Slide toward 0.

### Volume Guardrail

Even at knob=0.0, the orchestrator will not send 100% of traffic to psp-c. A minimum percentage (default: 10%) is reserved for secondary PSPs so they stay operationally active and Aplazo avoids a single point of failure.

> **Why it matters:** If psp-c gets 90%+ of volume and has an outage, the backup PSPs' connections to the banking rails have gone cold — they haven't processed real transactions in weeks. The guardrail keeps the pipes warm and pressured. It also protects PSP relationships: providers who see low volume start deprioritizing Aplazo in their queues.

### What the orchestrator outputs per transaction

| Output field | What it means | Example |
|-------------|---------------|---------|
| `recommended_psp` | Which PSP to send to right now | `psp-c` |
| `fallback_psps` | Ordered list if primary fails | `[psp-o, psp-e, psp-d]` |
| `retry` | Should we attempt this at all? | `True` |
| `retry_on_psp` | If it fails, which PSP goes next? | `psp-o` |
| `max_attempts` | Total ceiling on attempts | `5` |
| `stop_reason` | If retry=False, why | `hard decline: insufficient funds` |
| `expected_cost_pct` | Fee % on recommended PSP | `1.55%` |
| `expected_ar` | Historical AR for this issuer on this PSP | `81.2%` |

---

## Engine Rules Implemented

| Rule | Trigger | Action |
|------|---------|--------|
| Hard decline short-circuit | Error matches permanent failure pattern | Stop immediately, no retry |
| Cron batch cap | `collection_gateway` contains cron/batch/auto | Max 3 attempts instead of 5 |
| Issuer-aware routing | BIN match available + transaction on psp-c or psp-e | Route to highest AR PSP for that issuer |
| psp-e cron exclusion | Cron transaction | Exclude psp-e (collapses to 29–35% AR on batch) |
| Volume guardrail | Secondary PSP allocation | Maintain ≥10% traffic floor per secondary PSP |
| Knob-weighted scoring | All transactions | Score = (knob × AR_score) + (1−knob × cost_efficiency_score) |

---

## What v1 Intentionally Does NOT Do — and Why

These are not oversights. Each one was a deliberate decision.

### ❌ No machine learning model

To train an ML model that predicts "which PSP should I use for this transaction?", you need examples where you tried the same transaction on different PSPs and saw both outcomes. That data does not exist. The March dataset only shows what happened on the PSP that was actually used. If we train ML on that, it learns "psp-c is always great" — because psp-c always got the good transactions routed to it. That's a circular loop, not intelligence.

**What unlocks it:** Six months of A/B routing experiments — where we deliberately send 10% of traffic to random PSP assignment — generates the counterfactual data needed to train properly.  
**Roadmap:** v3 — after A/B experiment data is collected.

### ❌ No issuer routing for 62% of transactions

psp-o and psp-d — which together handle 62% of transaction volume — do not include the card's BIN number in their event data. Without the BIN, we cannot look up the issuer. Without the issuer, we cannot apply the issuer × PSP matrix. We route those transactions generically, exactly as today's static system does. No regression — just no improvement yet.

**What unlocks it:** A one-time data pipeline fix — ask psp-o and psp-d to include BIN in their webhook payloads.  
**Roadmap:** v2 priority #1 — before any ML work, before any new PSP integrations.

### ❌ No real-time approval rate updates

The issuer × PSP matrix is refreshed monthly from the analysis scripts. If a PSP starts degrading on a Tuesday afternoon, the orchestrator won't reflect it until next month's refresh. The Δ Margin alert in the Observability layer catches degradation within 4 hours, which is sufficient for v1.

**What unlocks it:** A production metrics store connected to the live event stream.  
**Roadmap:** v1.5 — the first infrastructure upgrade after v1 is stable.

### ❌ No SPEI / WhatsApp fallback channel

The brief scope is card transactions. SPEI is a bank transfer — a different payment rail entirely. Integrating it requires a separate API connection, different error handling, different reconciliation. But the data strongly justifies it: admin-dashboard has 8.2% approval because agents are retrying dead cards. After 2 failures, the card is not the right instrument.  
**Roadmap:** v1.5 — highest-impact product change for late-stage collection.

### ❌ No customer-level memory across installments

The orchestrator sees each transaction in isolation. It does not know that this is the same customer's 3rd failed installment in a row, or that they have 4 more installments due. The routing rules work correctly without it — they just can't prioritize "this customer always pays eventually" over "this customer has never paid."  
**Roadmap:** v2 — a lightweight customer reliability score from payment history.

---

## Roadmap

| Version | What ships | Why this order |
|---------|-----------|----------------|
| **v1 (now)** | Rules-based routing · Hard decline stop · Knob · Guardrail · Cron rules | Establishes baseline, earns operator trust, stops the most obvious waste immediately |
| **v1.5** | Hourly AR refresh · SPEI/WhatsApp fallback trigger · Real-time Δ Margin alert | Closes the detection gap and adds the highest-ROI channel switch without touching routing core |
| **v2** | BIN logging fix on psp-o/psp-d · A/B routing experiment framework · Customer reliability score | BIN fix unlocks issuer routing for 62% of volume — the single biggest quality jump available |
| **v3** | ML-based PSP scoring · Multi-method orchestration (card + SPEI + OXXO) · Continuous learning | ML only makes sense after A/B data exists and the rules have proven which signals matter |

---

## Known Data Gaps & Blind Spots

| Constraint | Impact | How it's handled |
|-----------|--------|-----------------|
| psp-o and psp-d have no BIN data | Cannot do issuer routing for ~62% of volume | Treated as generic fallbacks only |
| Only 21.3% of card rows matched a BIN | Issuer routing works for minority of transactions | Falls back to global AR estimates |
| psp-c × cron shows 100% AR — likely pre-auth captures | May inflate psp-c cron metrics | Flagged; needs engineering confirmation |
| Error messages inconsistently formatted | "insufficient funds" has 6+ variants | Normalized with lowercase + substring match |
| No latency data | Cannot pick faster PSP when AR is equal | Excluded from scoring |
| March data includes Semana Santa | Issuer × PSP rates may be holiday-specific | Must validate against 3+ non-adjacent months before production |
| No counterfactual routing data | True lift from orchestrator cannot be measured directly | A/B experiment needed — planned for v2 |

---

## Observability & Success Metrics

**North star metric:** Δ Margin = Revenue_collected(Orchestrator) − Revenue_collected(Static_baseline)

Four signals the operator monitors to know the system is healthy:

1. **Approval rate by PSP (hourly)** — If psp-c's AR drops more than 10pp from its baseline, alert immediately.
2. **Volume share by PSP** — Is psp-c getting 60%+ of traffic? Is the guardrail holding? Zero-traffic on any PSP means something is broken.
3. **Hard decline rate** — What percentage of transactions are stopped by the interceptor? A spike means either a new failure pattern is appearing (correct behavior) or the pattern matching is too aggressive (needs review).
4. **Retry depth distribution** — Most installments should resolve at attempt 1 or 2. A spike in attempt 4–5 events means first-attempt routing quality is degrading.

**Automatic safety net:** If Δ Margin drops below the static baseline for a sustained 4-hour window, revert to static routing and alert the operator.

---

## Scope Boundaries

**In scope:**
- Card transactions on all 4 PSPs
- Routing by card issuer, amount, gateway, and attempt history
- Hard decline detection and immediate stop
- Cron vs. user-initiated handling
- Cost vs. acceptance rate trade-off via The Knob
- Volume concentration guardrail

**Out of scope:**
- Alternative payment methods (SPEI, OXXO, digital wallets) — v1.5
- Latency optimization — no timing data available
- Independent fraud scoring — trusts error messages as-is
- Live ML model — rules derived from historical data, not real-time
- Merchant-level routing — no differentiation by store or product

---

## Glossary

| Term | Definition |
|------|-----------|
| **BNPL** | Buy Now, Pay Later. A financing model where a customer pays in installments over time instead of upfront. |
| **PSP** | Payment Service Provider. A company that processes card transactions on behalf of a merchant. |
| **Installment** | One scheduled payment within a loan. A 6-installment loan has 6 due dates, each collected separately. |
| **Approval Rate (AR)** | The percentage of payment attempts that succeed (status = "complete"). Measured per attempt or per installment. |
| **BIN** | Bank Identification Number. The first 6–8 digits of a card that identify the issuing bank, card type, and brand. |
| **Issuer** | The bank that gave the customer their card (e.g., Nu MX, BBVA, Bancoppel). |
| **Cron / Batch** | An automated system that runs payment attempts in bulk overnight, with no user present. |
| **Hard Decline** | A failure caused by a permanent condition (no funds, card expired, fraud flag). Retrying will never succeed. |
| **Soft Decline** | A failure caused by a temporary condition (timeout, bank unavailable). Worth retrying. |
| **The Knob** | A 0.0–1.0 parameter controlling whether the orchestrator prioritizes lower fees (0.0) or higher approval rates (1.0). |
| **Volume Guardrail** | A minimum traffic floor (e.g., 10%) that prevents 100% of transactions going to one PSP, reducing concentration risk. |
| **Collection Gateway** | The entry point through which a payment was initiated: user checkout, agent dashboard, or automated cron batch. |
| **Attempt-level AR** | % of individual payment submissions that are approved. Low (26%) because many installments are retried multiple times. |
| **Installment-level AR** | % of installments where at least one attempt eventually succeeded. Higher (82.5%) because retries often recover failures. |
| **Δ Margin** | The revenue difference between orchestrator routing and static baseline routing. The north star metric. |
| **A/B Routing Experiment** | Sending a split of traffic to a control group (static routing) and treatment group (orchestrator) to measure true lift. |

---

## Project Structure

| File | Purpose |
|------|---------|
| `orchestrator.py` | Core routing engine — the `PaymentOrchestrator` class with all decision logic |
| `app.py` | Interactive Streamlit Control Plane — Simulator, Formula, Data Findings, Product Story, Observability |
| `product_spec.html` | Complete product specification + panel defense guide (open in any browser, no server needed) |
| `analysis_summary.md` | Data analysis notes — key findings, methodology, blind spots |
| `product_narrative.md` | Written product narrative answering all challenge questions in plain language |
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
