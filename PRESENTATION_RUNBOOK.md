# PRESENTATION RUNBOOK — COMPLETE SCRIPT
## Aplazo · Thursday 2:30 PM · David Anderson panel

---

> **SETUP — Do this 10 minutes before the call**
> 1. Run `streamlit run app.py` → open `http://localhost:8501`
> 2. Leave it on the **Simulator tab**
> 3. Set Knob to **0.50**, Guardrail to **10%**
> 4. Close every other window. Only the app is visible.
> 5. This runbook goes on your phone or a second monitor — they never see it.

---

## ── OPENING ── (0:00 – 1:00) · No screen share yet

**SAY:**
> "Hi everyone, great to connect with the Aplazo team. Give me one second to share my screen."

*[Share screen — Simulator tab is now visible]*

> "Before I click anything, one sentence to frame everything you're about to see:
>
> The real product I built is a backend engine — a piece of code that sits between Aplazo and its payment processors, intercepts every card charge attempt in real time, and decides in milliseconds which processor to use and whether to retry or stop.
>
> What you're looking at right now is the control panel for that engine. In production, this is what the Payments Operations team uses to configure and stress-test the system — without writing a single line of code."

---

## ── WHY THIS EXISTS ── (1:00 – 2:00) · Still on Simulator tab — don't click anything yet

**SAY:**
> "Let me tell you the problem I found in the data before I built anything.
>
> Right now, Aplazo's routing is static. The system sends **55% of all card payments to one provider — psp-o** — by default. That provider approves **less than half** of those transactions. Meanwhile, psp-c, which is our **cheapest** provider AND has the **highest approval rate** at 73%, only receives 19% of traffic.
>
> Nobody made a bad decision. The rules were written once and never updated. The orchestrator fixes the default."

---

## ── DATA FINDINGS ── (2:00 – 4:00) · **CLICK: Data & Findings tab**

*[Screen now shows: Approval Rate definitions, then PSP Performance table]*

**SAY:**
> "I ran a deep analysis on 5.9 million payment events from March. Let me walk you through three findings that directly drove the design decisions."

*[Point at the PSP table on screen — they can see: psp-c 73.4%, psp-o 49.8%, psp-o has 54.8% of volume]*

> "**Finding one is the one you see right here.** psp-c is simultaneously our cheapest fee AND our best approval rate. psp-o has the most traffic but performs the worst. The data tells us this is a routing problem, not a performance problem."

*[Scroll down slightly — they now see the Issuer × PSP Matrix]*

> "**Finding two.** The bank that issued the card matters more than which processor you choose. Look at Nu MX — 81% approval on psp-c, but if you send that same Nu MX card to psp-e, it drops to 15%. That's a 66-point gap. On the other side, Banorte actually performs better on psp-e. Our system needs to know the bank before it picks the lane. This is the core intelligence behind the routing engine."

*[Scroll down — they now see the Retry Analysis and PSP-switch finding]*

> "**Finding three — and this one surprised me.** The industry assumption is: if a payment fails on Provider A, quickly try Provider B and it'll work. I tested this on half a million retry attempts in our data. Same provider retry: 50.6% success. Different provider retry: 50.5%. Statistically identical.
>
> A card that's declined because the account is empty doesn't care which company tries to charge it next. The money was never there. So the engine's entire focus is on getting the first routing decision right — not on building a smarter cascade."

---

## ── LIVE DEMO ── (4:00 – 6:30) · **CLICK: Simulator tab**

*[Screen shows the form — Knob at 0.50, all fields ready to fill]*

> "Let me show you three live scenarios."

---

### DEMO 1 · The Knob *(takes ~90 seconds)*

*[Set these fields — narrate as you do it:]*
- Transaction Amount: **850**
- Card Issuer: **Banco Mercantil del Norte**
- Collection Gateway: **nextpayment**
- Attempt Number: **1**
- Last Error: **None**
- **SLIDE KNOB TO 1.00**

**SAY:**
> "Banorte card. First attempt. I've moved the knob all the way to maximum acceptance — meaning the engine will prioritize approval rate above everything else."

*[CLICK: Route Transaction]*

*[Screen shows: recommended PSP = psp-e, Expected AR ~68.5%, scoring table visible]*

> "The engine picks psp-e. Why? Because for Banorte specifically, psp-e has a 68.5% approval rate versus psp-c's 60.7%. The scoring table right here shows the math — psp-e wins on the AR score."

*[Now SLIDE KNOB TO 0.00 — then CLICK: Route Transaction again]*

*[Screen now shows: recommended PSP = psp-c]*

> "I move the knob to zero — now cost is everything. Same Banorte card, same transaction, same moment. The engine flips to psp-c because it's the cheapest provider at 1.55%. The finance team can make this commercial trade-off in real time, no engineering ticket required."

---

### DEMO 2 · The Hard Stop *(takes ~60 seconds)*

*[Change the fields:]*
- Card Issuer: **Nu Mx**
- Attempt Number: **2**
- Last Error: **The card doesn't have sufficient funds**
- *(Knob can stay anywhere)*

**SAY:**
> "Nu MX card, second attempt, and the last error was insufficient funds."

*[CLICK: Route Transaction]*

*[Screen shows: 🚫 DO NOT RETRY banner, stop reason, reasoning chain shows Hard Decline Interceptor]*

> "Hard stop. The engine does not recommend a PSP. It does not suggest a retry. It shuts it down.
>
> Why? In our data, 771,000 transactions hit this exact error. The recovery rate on the next attempt is zero percent. If someone's account is empty, it doesn't matter which of the four providers you try next — the account is still empty. Every retry is a fee we pay for nothing.
>
> The cop stops the bleeding here."

---

### DEMO 3 · The Overnight Batch Rule *(takes ~60 seconds)*

*[Change the fields:]*
- Card Issuer: **Unknown / No BIN data**
- Collection Gateway: **cron**
- Attempt Number: **4**
- Last Error: **None**

**SAY:**
> "Last one. This is an automated overnight batch transaction — the kind that runs at 3am when no user is present. Attempt number 4."

*[CLICK: Route Transaction]*

*[Screen shows: 🚫 DO NOT RETRY, retry cap exceeded, reasoning shows Cron Channel Override]*

> "Blocked. For cron batch transactions, the retry cap is 3, not 5. Why? Because at 3am there's no user who can top up their account, call their bank, or switch to a different card. Attempts 4 and 5 are pure waste — we pay the fee, the card fails, nothing changes.
>
> Also notice: unknown card, no BIN data — this happens because psp-o and psp-d don't log card numbers in their event data. We literally cannot identify which bank issued the card for 62% of our volume. When that happens, the engine falls back to psp-c — our best default — and flags it. This is the single biggest infrastructure gap we'd fix in v2."

---

## ── PRODUCT STORY ── (6:30 – 8:30) · **CLICK: Product tab**

*[Screen shows: "Who is the operator?" section at the top, before/after table below it]*

**SAY — Who is the operator:**
> "The person who uses this system every day is the Payments Operations Lead — the person at Aplazo who owns collection performance. Not an engineer. They understand PSP contracts and approval rate trends but they cannot deploy code and should not have to.

> Today their job is reactive. Approval rates drop on a Monday morning report. They file a ticket to engineering. Two weeks later a fix ships. In those two weeks, every transaction that could have gone to a better processor is going to the wrong one — and nobody knows what that costs.

> With this system, they become proactive. They see issues before the Monday report. They respond to a PSP outage or a new pricing deal in minutes, without waiting for engineering."

*[Point at the before/after table on screen]*

> "Look at the before column — PSP goes down at 2am, an engineer wakes up, edits config, redeploys code, 45 minutes of misrouted traffic. With the orchestrator — operator raises the volume guardrail slider, traffic shifts automatically, recovery in under 2 minutes, no code."

*[Scroll down — Configuration Model section is now visible, with Fixed Rules and Operator Dials]*

**SAY — Configuration Model:**
> "The system has two types of inputs. Fixed rules — things the data told us are unambiguous and should never be overridden. And operator dials — business levers the ops team adjusts based on context, without touching code.

> Fixed rules: hard stop on permanent errors — 771,000 transactions per month hit 'insufficient funds' with zero recovery rate, so we stop immediately, no fee wasted. Cron batch cap at 3 attempts instead of 5 — overnight batch has no user present to fix anything, attempts 4 and 5 are pure waste. And psp-e is excluded from cron entirely — it collapses to 29% approval on batch, the data is unambiguous.

> Operator dials: the Knob you already saw. The Volume Guardrail. And the PSP fee table — when Finance signs a new contract at a better rate, they update one number and the scoring formula recalculates immediately for every future transaction."

**SAY — Why not ML:**
> "Before you ask — v1 is rules-based on purpose. Not because I couldn't build ML. Because ML needs a specific type of data I don't have: I need examples where the same transaction was sent to different PSPs and I saw both outcomes. The March data only shows what happened on the PSP that was actually used. If I train ML on that, it learns 'psp-c always wins' — because psp-c always got the good transactions routed to it. That's not intelligence, that's a circular loop. ML is v3, after A/B routing experiments generate the counterfactual data to train it properly."

*[Scroll down — "What v1 intentionally doesn't do" section is now visible]*

**SAY — What's missing and why:**
> "Four things are deliberately out of scope, and I want to name them before you ask.

> First: issuer routing for 62% of volume. psp-o and psp-d don't log BIN numbers in their event data — we literally can't identify which bank issued the card for those transactions. We route them generically, same as today. Not a regression, just a ceiling we can't break without a data pipeline fix on their side. That's v2 priority one.

> Second: SPEI and WhatsApp fallback. Admin-dashboard has 8.2% approval rate — agents retrying cards that customers have already drained. The right fix is sending a SPEI payment link via WhatsApp after 2 failures — different funding source entirely. But that requires integrating a second payment channel, which is outside the card-only scope of v1. That's v1.5.

> Third: real-time approval rate updates. The matrix refreshes monthly. A PSP could degrade on Tuesday and we won't reflect it until next month. Building a real-time streaming pipeline adds weeks of infrastructure complexity before we've even validated the routing logic works. The Δ Margin alert catches degradation within 4 hours — good enough for v1.

> Fourth: ML. Already covered."

*[Scroll down — Guardrails & Failure Modes section is now visible]*

**SAY — Failure modes:**
> "And I want to be honest about when this system makes things worse, because every system can.

> The most realistic failure mode: the approval rate matrix is stale. psp-c starts having a technical issue today — approval rate drops from 73% to 40%. The orchestrator doesn't know until next month's refresh. The mitigation is the hourly approval rate alert — if any PSP's observed rate drops more than 10 points below its matrix value, we get alerted and the operator overrides the routing manually.

> Second failure mode: a new Mexican neobank launches, its cards aren't in our BIN table. We can't identify the issuer. The system falls back to psp-c — which is still our best default. It never makes a worse decision than today's static routing. The floor is the baseline.

> Third: I found something suspicious in the data that I want to flag proactively. psp-c shows 100% approval rate on cron batch transactions. That number is not real — payment collections don't work that way. My hypothesis is these are pre-authorization captures being logged as approvals, not actual new charges. I excluded this from the cron baseline and flagged it — but it needs engineering to confirm before production rollout."

---

## ── OBSERVABILITY ── (8:30 – 9:30) · **CLICK: Observability tab**

*[Screen shows: Δ Margin formula at the top, then Core Alert Framework table, then metrics, then roadmap]*

**SAY — The north star metric:**
> "The single number that tells you whether this system is working or not is Δ Margin — the difference in revenue collected between the orchestrator and what the old static routing would have collected in the same window.

> We measure it on a rolling 4-hour window. If that number goes negative — meaning the orchestrator is collecting less than the naive baseline would — the system automatically reverts to static routing and pages the on-call team. There is no scenario where this system silently underperforms the status quo without us knowing."

*[Point at the Core Alert Framework table]*

> "Below the north star, there are five specific alerts. The red one is the auto-revert trigger — Δ Margin negative, immediate rollback. The yellow ones are early warnings: approval rate anomaly by issuer, concentration breach if one PSP gets too much traffic, and a hard decline surge. The blue ones are daily health checks — confirming the hard decline interceptor is saving money and the cron cap isn't too aggressive."

*[Point at the four metric tiles — 82.5%, 771K, 19%, TBD]*

> "The four numbers on this dashboard are what the operator checks every morning. Installment-level approval rate — are we still collecting 82.5% of installments? Hard declines stopped — is the interceptor working, 771K per month not being retried? psp-c share of volume — is it staying below 90% as the guardrail requires? And Δ Margin versus baseline — which today shows TBD because we haven't run a live A/B test yet."

**SAY — The A/B test:**
> "That last number is the honest gap in v1. I can show you that the routing logic is smarter than the static baseline in theory — and the issuer matrix numbers back that up. But I cannot show you the actual revenue lift in production without a split experiment.

> Here's how the A/B test works: we take 10% of live traffic and route it using the old static rules. The other 90% runs through the orchestrator. We compare Δ Margin between those two groups in real time. That gives us three things: the hard revenue number to justify continued investment, proof that the routing lift is real and not just statistical noise, and — most importantly — the counterfactual data we need to eventually train an ML model. The A/B experiment is not just a validation step. It is the data generation step for v3."

---

## ── CLOSE ── (9:30 – 10:00)

**SAY:**
> "That's the full system. Backend engine, control panel, data foundation, observability layer, and an honest roadmap of what comes next and why.

> I'm happy to go wherever you want from here."

---
---

# PANEL Q&A — What to say and where to click

---

### "Walk me through a transaction end to end."

**CLICK: Simulator tab**
Run: Nu MX · $1,450 · nextpayment · attempt 1 · no error

**SAY:**
> "Three gates in sequence. Gate one: is the error a permanent failure? No error here, so we pass. Gate two: are we at the retry cap? Attempt 1 of 5 — we pass. Gate three: score every PSP. For Nu MX, the issuer matrix shows psp-c at 81.2% and psp-e at 15.8%. Even at knob 0 — pure cost mode — psp-c still wins because it's also the cheapest. So we route to psp-c, expected AR 81.2%, fee $22.48 MXN. Fallback order is psp-o then psp-e last — we never send Nu MX to psp-e unless everything else fails."

---

### "Why rules-based and not ML?"

**STAY on Product Story tab — scroll to Configuration Model section**

**SAY:**
> "Two reasons. First: no counterfactual data. The March dataset only shows the outcome of the PSP that was actually used. To train ML properly I need split experiments where I sent the same transaction to different PSPs and saw both outcomes. That data doesn't exist yet. Second: trust. If the engine makes a wrong decision at 2am, the ops team needs to be able to read why. Rules are fully auditable. ML is a black box. Trust comes before complexity. ML is the v3 roadmap — after A/B experiments generate the training data."

---

### "What's the biggest thing missing from v1?"

**CLICK: Features tab — scroll to 'What v1 intentionally doesn't do' section**

**SAY:**
> "psp-o and psp-d don't log BIN data. That means 62% of our transaction volume routes without issuer intelligence — we can't apply the Nu MX or Banorte rules to those transactions because we don't know which bank issued the card. Fixing this is a one-time data pipeline change on their side. It's the first thing I'd do after v1 ships — it unlocks issuer routing for the majority of volume without touching any routing logic."

---

### "How do you know the orchestrator is working?"

**CLICK: Observability tab**

**SAY:**
> "The north star metric is Δ Margin — the difference in revenue collected between the orchestrator and the static baseline, measured on a rolling 4-hour window. If that number goes negative, the orchestrator is underperforming the naive baseline and we automatically revert to static routing while investigating. Four other alerts watch for: approval rate anomalies by issuer, concentration risk if one PSP gets more than 90% of traffic, a surge in hard declines, and cron collection rate drift."

---

### "What did you try that didn't work?"

**SAY — no click needed:**
> "I assumed switching PSPs on retry would be a meaningful signal. I built the retry analysis to quantify how much it helps. The answer was: 0.1 percentage point difference across half a million retries. That finding completely changed the architecture — instead of building a smart cascade engine, I built a smart first-attempt routing engine. The retry path exists as a safety net, not a strategy."

---

### "What if psp-c goes down?"

**CLICK: Simulator tab — point at the sidebar**

**SAY:**
> "The ops lead opens this panel and raises the volume guardrail — that forces traffic to the secondary PSPs immediately, no code deploy. Recovery is under 2 minutes. The Δ Margin alert would have already fired before they even notice manually, because psp-c's contribution to approvals would have dropped to zero on the 4-hour window."

---

### "What are the failure modes?"

**CLICK: Blind Spots tab**

**SAY:**
> "Three realistic ones. One: the approval rate matrix is refreshed monthly — if psp-c degrades on a Tuesday, we route to it as if it's still healthy until next month's refresh. The Δ Margin alert catches this within 4 hours. Two: new card issuers not in our BIN table get no issuer routing — they fall back to psp-c, which is still better than random, but not optimal. Three: I found that psp-c shows 100% approval rate on cron batch, which is suspicious. My hypothesis is those are pre-authorization captures being logged as approvals, not real new charges. I flagged it and excluded it from the cron baseline — but it needs engineering to confirm before production."

---

### "How does the operator adjust to a new PSP deal?"

**SAY — no click needed:**
> "They update one number in the fee config table. The scoring formula recalculates immediately for every future transaction. No engineering ticket, no code deploy, no sprint. The knob handles the commercial philosophy — slide toward cost to favor the cheaper PSP, slide toward acceptance to favor the higher-performing one."

---

### "You said only 21% of rows matched a BIN. Why is that?"

**CLICK: Data & Findings tab — scroll to Data Quality Issues table**

**SAY:**
> "Two reasons. First, psp-o and psp-d log zero BIN data in their event payloads — their webhooks strip it before it hits our pipeline. That alone accounts for most of the gap since those two PSPs handle 62% of volume. Second, the bins_data.csv reference file has 1,282 entries, which doesn't cover every issuer. When both psp-c and psp-e log a BIN that isn't in our reference file, we also get no match. The fix is two-pronged: get psp-o/psp-d to log BINs, and expand the reference file."

---

# ONE SENTENCE FOR ANYTHING YOU BLANK ON

> *"That's a great question — I flagged that as a known gap going into v1. Let me show you where it sits on the roadmap."*
>
> → Click **Features tab** → scroll to "What v1 intentionally doesn't do"

---

> **Remember:** You built this. Every number you say came from the data you analyzed. If they push back on a number, say: *"Let me pull that up"* and go to Data & Findings. The data is right there.
