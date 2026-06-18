# Product Narrative — Aplazo Payment Orchestrator V1

---

## Who is the operator?

The operator is a payments ops lead — someone on the Aplazo team who is responsible for making sure customers' loan installments actually get collected. They are not a software engineer. They should not need to write code to do their job.

**Without this system, their day looks like this:**
- Monday morning: open a spreadsheet report from last week. Notice that approval rates dropped on a certain card type. File a ticket to engineering. Wait 2 weeks for a fix to ship. Meanwhile, money is being lost every day.
- They are always reacting. They find out something is broken after the damage is done.
- Every routing change — even a small one like "stop using this PSP for overnight batch" — requires an engineer to deploy new code.

**With this system, their day looks like this:**
- Open the Streamlit dashboard. See live approval rate by PSP, by card type, by collection channel.
- If something drops (say, Bancoppel cards are failing on psp-e today), they can see it in minutes, not days.
- They adjust the Optimization Knob — slide it toward "Max Acceptance" if they need to prioritize getting payments through no matter the cost, or toward "Min Cost" if margins are tight this week.
- No code deploy. No engineering ticket. The system re-routes immediately.
- If a new PSP contract comes in with a better fee, they update one number in a config table and the scoring formula recalculates automatically for every future transaction.

**The key shift:** from reactive firefighter to proactive system manager.

---

## What is the configuration model?

The system uses **fixed rules with a tunable dial**. Not pure machine learning, not a fully static rulebook — a deliberate mix.

Here is what is fixed and why:

| Rule | What it does | Why it's fixed |
|------|-------------|----------------|
| Hard stop on permanent failures | If the error says "insufficient funds" or "stolen card," stop immediately — don't retry | These errors will never resolve. Retrying them wastes money on transaction fees and damages Aplazo's reputation with the PSP |
| Max 3 attempts for overnight batch | Automated batch runs cap at 3 tries instead of 5 | There is no user present to fix the problem. Attempt 4 and 5 are almost always wasted |
| Never route cron batch to psp-e | psp-e collapses to 29–35% approval on automated batch | The data is unambiguous. This is not a judgment call |
| Keep minimum 10% traffic on secondary PSPs | Always send at least 10% of transactions to non-primary processors | Without this, secondary PSPs degrade over time — they stop investing in the relationship, their systems get cold, and when psp-c has an outage you have nowhere to fail over |

Here is what the operator can tune:

**The Optimization Knob (0 to 1)**
- At 0: the system always picks the cheapest PSP that can get the job done
- At 1: the system always picks the PSP most likely to approve the transaction, regardless of cost
- At 0.5 (default): it balances both — what we recommend for normal operation

This knob lets the operator respond to business context without touching code. End-of-month pressure on collections? Slide toward 1. Margin review week? Slide toward 0.

**PSP outage scenario:** If psp-c goes down, the operator sets psp-c's availability to false in the config. The system immediately routes to the next best option for each transaction type. No code change. Recovery is one field update.

**New PSP deal:** If Aplazo negotiates a better fee with psp-o, the operator updates the fee from 1.58% to 1.40% in the config table. Every future transaction scoring recalculates instantly.

---

## What are the guardrails?

Three things that prevent the system from making things worse:

**1. The hard decline short-circuit**
If the last error message signals a permanent failure, the system stops. It does not try another PSP. Permanent failures do not get better with more attempts — they just cost more money per failed try. Without this guardrail, the system would cascade through all four PSPs on a card that is never going to pay. With it, we cut that waste immediately.

**2. The volume guardrail (the 10% floor)**
The system will never send less than 10% of total transactions to secondary PSPs, even if psp-c is the best choice for almost everything. Why? Because if 90%+ of volume runs through one provider and that provider has an outage, Aplazo's collection operation stops entirely. This floor keeps the backup pipes warm and pressured. It also protects the PSP relationship — providers who see low volume start deprioritizing Aplazo in their queues.

**3. Fallback to psp-c**
If the system cannot determine the best route (no BIN data, unknown issuer, ambiguous error), it falls back to psp-c — the cheapest and highest-performing PSP overall. The worst-case decision is the historically best provider. The system cannot fall below the baseline.

**When would the orchestrator make a worse decision than today's static logic?**
The most realistic failure mode is a sudden shift in a PSP's behavior that the system does not detect fast enough. For example: psp-c starts having an undisclosed technical issue and its approval rate drops from 73% to 40% this morning. The orchestrator keeps routing to psp-c because it does not know yet. The observability layer (approval rate alerts) would catch this within hours — but there is a window of damage. The mitigation for V2 is real-time AR monitoring with automatic circuit-breaker thresholds.

---

## What does observability look like?

Four things the operator needs to see to know the system is healthy:

**1. Approval rate by PSP, updated hourly**
The most important number. If psp-c's AR drops more than 10 percentage points from its baseline, something is wrong. Alert immediately.

**2. Volume share by PSP**
Is psp-c getting 60%+ of traffic as expected? Is the volume guardrail holding? If any PSP is getting 0% traffic, something is broken — either in routing logic or in that PSP's connection.

**3. Hard decline rate**
What percentage of transactions are being stopped by the hard decline short-circuit? If this number spikes, it might mean a new error pattern is appearing that the system is correctly catching — or it might mean the pattern matching is being too aggressive and stopping recoverable transactions.

**4. Retry depth distribution**
How many transactions are reaching attempt 2, 3, 4, 5? If the system is working, the majority of installments should resolve at attempt 1 or 2. A spike in attempt 4–5 events means first-attempt routing quality is degrading and needs investigation.

---

## What is V1 missing intentionally?

**ML-based routing** — V1 does not learn. It follows rules derived from historical data. This was intentional for three reasons:
- The ops team needs to be able to audit every decision. A rules-based system is fully transparent. If a transaction routes wrong, you can point to exactly which rule fired and why.
- To train an ML model that predicts "what would psp-e's AR be for *this* transaction if we had routed it there?", we need experiments where we deliberately split traffic and compare outcomes. We do not have that data yet.
- Rules already capture most of the variance. The issuer × PSP matrix explains the majority of approval rate differences. ML on top of that is complexity without clear payoff in V1.

**Issuer routing for psp-o and psp-d** — 62% of transaction volume goes through PSPs that do not log BIN data. We cannot do issuer-level routing for those transactions today. We route them generically, which is the same as what the current system does. No regression — just no improvement yet.

**Installment-level intelligence** — we know a customer has multiple installments. We do not yet use that information. If a customer has 3 installments and the first two failed on the same card, that is a signal that the card itself is the problem, not the routing. V2 should incorporate this.

---

## What does V2 and V3 look like?

**V2 (next 60–90 days):**
- Get psp-o and psp-d to log BIN data. This one infrastructure fix unlocks issuer routing for the 62% of volume that is currently routed blind. Highest ROI change available.
- Run a proper A/B routing experiment: send 10% of traffic to the legacy static routing as a control group. Measure the actual revenue lift from the orchestrator in real numbers — not hypothetical, not extrapolated, real.
- Add real-time circuit breakers: if any PSP's approval rate drops more than 15pp in a 1-hour window, automatically reduce its traffic share and alert the operator.

**V3 (3–6 months out):**
- Use the A/B experiment data to train an ML model that learns the optimal PSP for each transaction from actual outcomes — not just the average per issuer, but per customer segment, time of day, amount tier, funding type.
- Incorporate installment-level data: customer payment history, number of open installments, past failure patterns.
- Add payment method routing: when a card fails twice on the same installment, the system should automatically trigger a SPEI or WhatsApp payment link — changing the channel entirely, not just the PSP. This is especially relevant for the admin-dashboard gateway, which currently operates at 8.2% approval rate because agents are retrying cards that will never pay.

---

## On using AI in this project

AI was used as an execution tool, not a thinking tool. Every hypothesis, every cut in the data, every design decision was directed by me.

**Specific examples of where I caught the model and overrode it:**
- The model initially suggested that switching PSPs on retry would improve outcomes. I pushed back and ran the data: switching PSP yields 50.5% AR vs. 50.6% for same-PSP retries — statistically identical. The insight is the opposite of the intuition: retry strategy does not matter, first-attempt routing does. The model would have built a smarter cascade. I built a smarter first decision instead.
- The model flagged psp-c × cron batch as having 100% approval rate. That number is suspicious — real transactions do not work that way. My hypothesis is that these are pre-authorization captures being logged as approvals, not actual new payment approvals. I flagged it as a data artifact, not a finding, and did not build routing logic on top of it.
- The Volume Guardrail slider in the Streamlit app was showing "0%–0%" because the model used a float slider (0.10 displayed as "0%"). I identified the root cause — format string mismatch — and fixed it with an integer slider (0–30, divided by 100).

**What I cannot explain, I did not include.**
Every number in this submission I can trace back to the data. Every rule I can explain the reasoning for. That is the bar I held throughout.
