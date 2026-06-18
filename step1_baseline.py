"""
Payment Orchestrator - Step 1: Analytical Baseline & Data Cleaning
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────
print("Loading data...")

events = pd.read_csv("payment_events-march2026.csv", low_memory=False)
loans  = pd.read_csv("loans_data-march2026.csv",     low_memory=False)
bins   = pd.read_csv("bins_data.csv",                low_memory=False)

print(f"  events:  {len(events):,} rows")
print(f"  loans:   {len(loans):,} rows")
print(f"  bins:    {len(bins):,} rows")

# ─────────────────────────────────────────────
# 2. CLEAN STRING COLUMNS
# ─────────────────────────────────────────────
def clean_str(s):
    """Lowercase, strip whitespace, replace empty/whitespace-only with NaN."""
    if pd.api.types.is_string_dtype(s):
        s = s.str.strip().str.lower()
        s = s.replace(r'^\s*$', np.nan, regex=True)
    return s

str_cols = ["payment_status", "payment_processor", "payment_type",
            "payment_method", "collection_gateway", "error_message", "error_code"]

for col in str_cols:
    if col in events.columns:
        events[col] = clean_str(events[col])

events["event_timestamp"] = pd.to_datetime(
    events["event_timestamp"].str.replace(" UTC", "", regex=False),
    format="mixed", utc=True
)

# ─────────────────────────────────────────────
# 3. SCOPE FILTER — CARD ONLY
# ─────────────────────────────────────────────
card_events = events[events["payment_method"] == "card"].copy()
print(f"\nCard-only rows: {len(card_events):,}  ({len(card_events)/len(events)*100:.1f}% of total)")

# ─────────────────────────────────────────────
# 4. CRON FLAG
# ─────────────────────────────────────────────
# Cron jobs typically fire in early morning hours (midnight–6am Mexico City = UTC-6, so 06:00–12:00 UTC)
# Flag by hour bucket; also flag if collection_gateway contains 'cron' or 'auto'
card_events["hour_utc"] = card_events["event_timestamp"].dt.hour
card_events["is_cron"] = (
    card_events["collection_gateway"].str.contains("cron|auto|batch|schedule", na=False) |
    card_events["hour_utc"].between(6, 12)  # 00:00–06:00 MX time
)
print(f"Cron-flagged transactions: {card_events['is_cron'].sum():,}  ({card_events['is_cron'].mean()*100:.1f}%)")

# ─────────────────────────────────────────────
# 5. APPROVAL RATE DEFINITIONS
# ─────────────────────────────────────────────
# Attempt-level: 1 row = 1 attempt; approved if status == 'complete'
card_events["is_approved"] = (card_events["payment_status"] == "complete").astype(int)
card_events["is_terminal"]  = card_events["payment_status"].isin(["complete", "failed"])

# Installment-level: an installment is "collected" if ANY attempt succeeded
installment_outcome = (
    card_events[card_events["is_terminal"]]
    .groupby("installment_id")
    .agg(
        attempts         = ("event_id",    "count"),
        any_approved     = ("is_approved", "max"),
        installment_amount = ("installment_amount", "first"),
    )
    .reset_index()
)

attempt_ar    = card_events["is_approved"].mean()
installment_ar = installment_outcome["any_approved"].mean()
print(f"\nApproval Rate (attempt-level):      {attempt_ar*100:.2f}%")
print(f"Approval Rate (installment-level):  {installment_ar*100:.2f}%")

# ─────────────────────────────────────────────
# 6. APPROVAL RATE CUTS
# ─────────────────────────────────────────────

def ar_table(df, groupby_col, label=None):
    label = label or groupby_col
    g = (
        df[df["is_terminal"]]
        .groupby(groupby_col, dropna=False)
        .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
        .assign(approval_rate=lambda x: x["approvals"] / x["attempts"])
        .sort_values("approval_rate", ascending=False)
    )
    print(f"\n── Approval Rate by {label} ──")
    print(g.to_string())
    return g

ar_psp     = ar_table(card_events, "payment_processor", "PSP")
ar_gateway = ar_table(card_events, "collection_gateway", "Collection Gateway")

# BIN join for issuer-level
bins_slim = bins[["card_bin", "card_bank_normalized", "card_type", "card_brand"]].copy()
bins_slim.columns = ["bin", "issuer", "card_type", "card_brand"]
bins_slim["bin"] = bins_slim["bin"].astype(str)
card_events["bin_str"] = card_events["bin"].astype(str)
card_with_bin = card_events.merge(bins_slim, left_on="bin_str", right_on="bin", how="left")

ar_issuer = ar_table(card_with_bin, "issuer", "Issuer (top 20)").head(20)

# Amount tiers
card_events["amount_tier"] = pd.cut(
    card_events["installment_amount"],
    bins=[0, 200, 500, 1000, 2000, 5000, np.inf],
    labels=["0-200", "200-500", "500-1k", "1k-2k", "2k-5k", "5k+"]
)
ar_amount = ar_table(card_events, "amount_tier", "Amount Tier")

# Hour-of-day
card_events["hour_bucket"] = pd.cut(
    card_events["hour_utc"],
    bins=[0, 6, 12, 18, 24],
    labels=["00-06 UTC", "06-12 UTC", "12-18 UTC", "18-24 UTC"],
    right=False
)
ar_hour = ar_table(card_events, "hour_bucket", "Hour Bucket (UTC)")

# PSP × Gateway cross-cut
print("\n── Approval Rate: PSP × Gateway ──")
cross = (
    card_events[card_events["is_terminal"]]
    .groupby(["payment_processor", "collection_gateway"], dropna=False)
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(approval_rate=lambda x: x["approvals"] / x["attempts"])
    .sort_values("approval_rate", ascending=False)
)
print(cross.to_string())

# ─────────────────────────────────────────────
# 7. RETRY ANALYSIS
# ─────────────────────────────────────────────
print("\n── Retry Analysis ──")

# Sort events per installment by timestamp to assign attempt number
card_events_sorted = (
    card_events[card_events["is_terminal"]]
    .sort_values(["installment_id", "event_timestamp"])
    .copy()
)
card_events_sorted["attempt_n"] = (
    card_events_sorted.groupby("installment_id").cumcount() + 1
)

# Approval rate at each attempt number
ar_by_attempt = (
    card_events_sorted
    .groupby("attempt_n")
    .agg(attempts=("is_approved","count"), approvals=("is_approved","sum"))
    .assign(approval_rate=lambda x: x["approvals"] / x["attempts"])
)
print("\nApproval Rate per Attempt #:")
print(ar_by_attempt.head(10).to_string())

# Error codes that never recover on retry
print("\n── Error Messages: Recovery Rate on Next Attempt ──")
# For each failed attempt, check if the NEXT attempt on the same installment succeeded
failed = card_events_sorted[card_events_sorted["payment_status"] == "failed"].copy()
failed["next_status"] = (
    failed.sort_values("attempt_n")
    .groupby("installment_id")["is_approved"]
    .shift(-1)
)

error_recovery = (
    failed
    .groupby("error_message", dropna=False)
    .agg(
        occurrences    = ("event_id",    "count"),
        next_attempt_ar = ("next_status", "mean"),
    )
    .sort_values("occurrences", ascending=False)
    .head(30)
)
print(error_recovery.to_string())

print("\n✓ Step 1 complete.")
