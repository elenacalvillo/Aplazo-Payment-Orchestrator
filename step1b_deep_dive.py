"""
Payment Orchestrator - Step 1b: Hidden Stories Deep Dive
Credit vs Debit split per PSP + Volume concentration + additional cuts
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

print("Loading data...")
events = pd.read_csv("payment_events-march2026.csv", low_memory=False)
bins   = pd.read_csv("bins_data.csv", low_memory=False)

# ── Clean ──────────────────────────────────────────────────────────────────
str_cols = ["payment_status","payment_processor","payment_type",
            "payment_method","collection_gateway","error_message","error_code"]
for col in str_cols:
    if col in events.columns:
        events[col] = events[col].str.strip().str.lower()
        events[col] = events[col].replace(r'^\s*$', np.nan, regex=True)

events["event_timestamp"] = pd.to_datetime(
    events["event_timestamp"].str.replace(" UTC","",regex=False),
    format="mixed", utc=True
)

card = events[events["payment_method"] == "card"].copy()
card["is_approved"] = (card["payment_status"] == "complete").astype(int)
card["is_terminal"]  = card["payment_status"].isin(["complete","failed"])

# BIN join — bring in card_funding_type (credit/debit) and card_bank_normalized
bins_slim = bins[["card_bin","card_funding_type","card_bank_normalized","card_brand"]].copy()
bins_slim["card_bin"] = bins_slim["card_bin"].astype(str)
card["bin_str"] = card["bin"].astype(str)
card = card.merge(bins_slim, left_on="bin_str", right_on="card_bin", how="left")

matched_pct = card["card_funding_type"].notna().mean() * 100
print(f"BIN match rate: {matched_pct:.1f}% of card rows have funding type\n")

terminal = card[card["is_terminal"]].copy()

# ══════════════════════════════════════════════════════════════════════════
# CUT 1 — PSP × Credit vs Debit
# ══════════════════════════════════════════════════════════════════════════
print("=" * 65)
print("CUT 1: Approval Rate by PSP × Card Funding Type (Credit / Debit)")
print("=" * 65)

psp_funding = (
    terminal
    .groupby(["payment_processor","card_funding_type"], dropna=False)
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(ar=lambda x: (x["approvals"]/x["attempts"]*100).round(1))
    .reset_index()
)
print(psp_funding.to_string(index=False))

# Pivot for readability
pivot = psp_funding.pivot_table(
    index="payment_processor",
    columns="card_funding_type",
    values=["ar","attempts"],
    aggfunc="first"
).round(1)
print("\nPivot (AR% | attempts):")
print(pivot.to_string())

# ══════════════════════════════════════════════════════════════════════════
# CUT 2 — Volume Concentration per PSP
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 2: Volume Concentration across PSPs")
print("=" * 65)

vol = (
    terminal
    .groupby("payment_processor", dropna=False)
    .agg(
        attempts      = ("is_approved","count"),
        approvals     = ("is_approved","sum"),
        total_amount  = ("installment_amount","sum"),
        approved_amount = ("installment_amount", lambda x:
                           x[terminal.loc[x.index,"is_approved"]==1].sum()),
    )
    .assign(
        share_of_attempts   = lambda x: (x["attempts"]  / x["attempts"].sum()  * 100).round(1),
        share_of_approved_vol= lambda x: (x["approvals"]/ x["approvals"].sum() * 100).round(1),
        ar                  = lambda x: (x["approvals"] / x["attempts"]         * 100).round(1),
    )
    .sort_values("attempts", ascending=False)
)
print(vol[["attempts","share_of_attempts","approvals","share_of_approved_vol","ar"]].to_string())

# ══════════════════════════════════════════════════════════════════════════
# CUT 3 — PSP × Credit/Debit × Amount Tier
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 3: AR by PSP × Funding Type × Amount Tier")
print("=" * 65)

terminal["amount_tier"] = pd.cut(
    terminal["installment_amount"],
    bins=[0,200,500,1000,2000,np.inf],
    labels=["0-200","200-500","500-1k","1k-2k","2k+"]
)
cut3 = (
    terminal[terminal["card_funding_type"].isin(["credit","debit"])]
    .groupby(["payment_processor","card_funding_type","amount_tier"], dropna=False)
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(ar=lambda x: (x["approvals"]/x["attempts"]*100).round(1))
    .reset_index()
)
print(cut3.to_string(index=False))

# ══════════════════════════════════════════════════════════════════════════
# CUT 4 — Cron vs Non-Cron per PSP (Credit / Debit split)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 4: Is cron the channel polluting PSP-D and PSP-O?")
print("        AR by PSP × Cron × Funding Type")
print("=" * 65)

terminal["is_cron"] = terminal["collection_gateway"].str.contains(
    "cron|auto|batch|schedule", na=False
)
cut4 = (
    terminal[terminal["card_funding_type"].isin(["credit","debit"])]
    .groupby(["payment_processor","is_cron","card_funding_type"], dropna=False)
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(ar=lambda x: (x["approvals"]/x["attempts"]*100).round(1))
    .reset_index()
)
print(cut4.to_string(index=False))

# ══════════════════════════════════════════════════════════════════════════
# CUT 5 — admin-dashboard: what errors dominate?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 5: admin-dashboard-nextpayment — top failure reasons")
print("=" * 65)

admin = terminal[
    (terminal["collection_gateway"] == "admin-dashboard-nextpayment") &
    (terminal["payment_status"] == "failed")
]
print(admin["error_message"].value_counts().head(15).to_string())

# ══════════════════════════════════════════════════════════════════════════
# CUT 6 — Issuer × PSP: which issuers work better on which PSP?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 6: Top Mexican issuers — which PSP approves them best?")
print("=" * 65)

# Focus on the issuers with enough volume to be meaningful (>1000 attempts)
big_issuers = (
    terminal.groupby("card_bank_normalized")["is_approved"]
    .count()
    .pipe(lambda s: s[s >= 1000])
    .index
)
cut6 = (
    terminal[terminal["card_bank_normalized"].isin(big_issuers)]
    .groupby(["card_bank_normalized","payment_processor"])
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(ar=lambda x: (x["approvals"]/x["attempts"]*100).round(1))
    .reset_index()
    .pivot_table(index="card_bank_normalized", columns="payment_processor",
                 values="ar", aggfunc="first")
    .round(1)
)
# Add total volume for context
vol_issuer = terminal[terminal["card_bank_normalized"].isin(big_issuers)].groupby("card_bank_normalized")["is_approved"].count()
cut6["total_attempts"] = vol_issuer
cut6 = cut6.sort_values("total_attempts", ascending=False)
print(cut6.to_string())

# ══════════════════════════════════════════════════════════════════════════
# CUT 7 — Retry pattern: does switching PSP on retry help?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("CUT 7: Does switching PSP on retry improve approval rate?")
print("=" * 65)

sorted_ev = (
    card[card["is_terminal"]]
    .sort_values(["installment_id","event_timestamp"])
    .copy()
)
sorted_ev["attempt_n"] = sorted_ev.groupby("installment_id").cumcount() + 1
sorted_ev["prev_psp"]  = sorted_ev.groupby("installment_id")["payment_processor"].shift(1)
sorted_ev["psp_switched"] = (
    sorted_ev["payment_processor"] != sorted_ev["prev_psp"]
) & sorted_ev["prev_psp"].notna()

retries = sorted_ev[sorted_ev["attempt_n"] > 1]
switch_ar = (
    retries.groupby("psp_switched")
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(ar=lambda x: (x["approvals"]/x["attempts"]*100).round(1))
)
switch_ar.index = ["Same PSP","Switched PSP"]
print(switch_ar.to_string())

print("\n✓ Step 1b complete.")
