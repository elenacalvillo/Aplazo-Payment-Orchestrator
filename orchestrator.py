"""
Payment Orchestrator — Aplazo BNPL
Steps 2 & 3: Cost Modeling + Routing Engine
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# STATIC KNOWLEDGE TABLES  (derived from Step 1 analysis)
# ─────────────────────────────────────────────────────────────────────────────

PSP_FEES: dict[str, float] = {
    "psp-c": 0.0155,
    "psp-o": 0.0158,
    "psp-e": 0.0168,
    "psp-d": 0.0169,
}

# Approval rates from Step 1b Cut 6 — only where we have BIN signal.
# psp-o and psp-d have no BIN event data → treated as generic fallbacks.
ISSUER_PSP_AR: dict[str, dict[str, float]] = {
    "nu mx":                    {"psp-c": 0.812, "psp-e": 0.158},
    "bancoppel":                {"psp-c": 0.809, "psp-e": 0.600},
    "banco santander":          {"psp-c": 0.723, "psp-e": 0.332},
    "banco azteca":             {"psp-c": 0.702, "psp-e": 0.373},
    "banco nacional de mx":     {"psp-c": 0.688, "psp-e": 0.224},
    "bbva":                     {"psp-c": 0.517, "psp-e": 0.422},
    "compropago":               {"psp-c": 0.779, "psp-e": 0.214},
    "hsbc":                     {"psp-c": 0.777, "psp-e": 0.433},
    "klar":                     {"psp-c": 0.762, "psp-e": 0.282},
    "mercado libre":            {"psp-c": 0.822, "psp-e": 0.294},
    "regigold":                 {"psp-c": 0.828, "psp-e": 0.544},
    "uala":                     {"psp-c": 0.848, "psp-e": 0.329},
    "banco mercantil del norte":{"psp-c": 0.607, "psp-e": 0.685},  # psp-e wins
    "stori":                    {"psp-c": 0.580, "psp-e": 0.162},
    "banregio":                 {"psp-c": 0.815, "psp-e": 0.297},
    "banco compartamos":        {"psp-c": 0.604, "psp-e": 0.188},
    "banco invex":              {"psp-c": 0.800, "psp-e": 0.302},
    "scotiabank":               {"psp-c": 0.607, "psp-e": 0.292},
    "openbank":                 {"psp-c": 0.790, "psp-e": 0.000},
    "banca afirme":             {"psp-c": 0.690, "psp-e": 0.509},
    "banca mifel":              {"psp-c": 0.750, "psp-e": 0.408},
    "truu innovation":          {"psp-c": 0.840, "psp-e": 0.067},
    # Critically low — no PSP performs well; route to cheapest + hard retry cap
    "bradescard":               {"psp-c": 0.003, "psp-e": 0.261},
    "liverpool":                {"psp-c": 0.099, "psp-e": 0.194},
}

# Errors that guarantee zero recovery value on any retry
HARD_DECLINE_PATTERNS: tuple[str, ...] = (
    "insufficient funds",
    "insufficient_funds",
    "the card doesn't have sufficient funds",
    "fondos insuficientes",
    "fraud risk detected",
    "card country not authorized",
    "exceeded max attempts",
    "the card was reported as lost",
    "the card has expired",
    "expired card",
    "expired_card",
)

# PSPs with confirmed BIN-level routing signal
BIN_AWARE_PSPS: frozenset[str] = frozenset({"psp-c", "psp-e"})

# Generic fallback priority when no issuer signal exists
GENERIC_FALLBACK_ORDER: list[str] = ["psp-c", "psp-o", "psp-e", "psp-d"]


# ─────────────────────────────────────────────────────────────────────────────
# DATA TYPES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Transaction:
    amount:          float
    issuer:          Optional[str]   = None   # card_bank_normalized from BIN table
    funding_type:    Optional[str]   = None   # "credit" | "debit" | "prepaid"
    gateway:         Optional[str]   = None   # collection_gateway
    is_cron:         bool            = False
    error_message:   Optional[str]   = None   # populated on a retry attempt
    attempt_number:  int             = 1

    def __post_init__(self):
        if self.issuer:
            self.issuer = self.issuer.strip().lower()
        if self.error_message:
            self.error_message = self.error_message.strip().lower()
        # Infer cron from gateway if not explicitly set
        if self.gateway and not self.is_cron:
            self.is_cron = "cron" in self.gateway.lower()


@dataclass
class RoutingDecision:
    recommended_psp:  str
    fallback_psps:    list[str]
    retry:            bool
    retry_on_psp:     Optional[str]
    max_attempts:     int
    stop_reason:      Optional[str]
    expected_cost_pct: float
    expected_ar:      Optional[float]
    notes:            list[str] = field(default_factory=list)

    def display(self):
        print(f"  recommended_psp  : {self.recommended_psp}")
        print(f"  fallback_psps    : {self.fallback_psps}")
        print(f"  retry            : {self.retry}")
        print(f"  retry_on_psp     : {self.retry_on_psp}")
        print(f"  max_attempts     : {self.max_attempts}")
        print(f"  stop_reason      : {self.stop_reason or '—'}")
        print(f"  expected_cost_%%  : {self.expected_cost_pct*100:.2f}%%")
        if self.expected_ar:
            print(f"  expected_ar      : {self.expected_ar*100:.1f}%%")
        if self.notes:
            for n in self.notes:
                print(f"  ⚠  {n}")


# ─────────────────────────────────────────────────────────────────────────────
# THE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class PaymentOrchestrator:
    """
    Routes a single transaction to the optimal PSP and defines its retry policy.

    knob : float [0.0 – 1.0]
        0.0 → minimise cost   (default to cheapest PSP; accept lower AR)
        1.0 → maximise AR     (route by issuer-PSP performance matrix)
        0.5 → balanced        (recommended for production baseline)

    volume_guardrail : float
        Minimum fraction of total traffic each secondary PSP must receive.
        Prevents 100% concentration in psp-c even when knob=0.0.
        Default 0.10 (10%).
    """

    def __init__(self, knob: float = 0.5, volume_guardrail: float = 0.10):
        if not 0.0 <= knob <= 1.0:
            raise ValueError("knob must be between 0.0 and 1.0")
        self.knob = knob
        self.volume_guardrail = volume_guardrail
        # Simulated rolling traffic share (in a real system this comes from a
        # metrics store; here we use a stub so the guardrail logic is testable)
        self._traffic_share: dict[str, float] = {
            "psp-c": 0.50, "psp-o": 0.25, "psp-e": 0.15, "psp-d": 0.10
        }

    # ── public interface ────────────────────────────────────────────────────

    def route(self, tx: Transaction) -> RoutingDecision:
        """Evaluate a transaction and return a full routing + retry decision."""

        # 1. Hard decline check — no retry, no routing deliberation needed
        if tx.error_message and self._is_hard_decline(tx.error_message):
            return RoutingDecision(
                recommended_psp   = "none",
                fallback_psps     = [],
                retry             = False,
                retry_on_psp      = None,
                max_attempts      = tx.attempt_number,
                stop_reason       = f"hard decline: {tx.error_message}",
                expected_cost_pct = 0.0,
                expected_ar       = 0.0,
                notes             = ["Hard decline pattern — no retry value."],
            )

        # 2. Max retry gate — Step 1 shows AR collapses after attempt 5
        max_attempts = self._max_attempts_policy(tx)
        if tx.attempt_number >= max_attempts:
            return RoutingDecision(
                recommended_psp   = "none",
                fallback_psps     = [],
                retry             = False,
                retry_on_psp      = None,
                max_attempts      = max_attempts,
                stop_reason       = f"retry cap reached (attempt {tx.attempt_number}/{max_attempts})",
                expected_cost_pct = 0.0,
                expected_ar       = None,
                notes             = [],
            )

        # 3. Resolve PSP ranking for this transaction
        ranked = self._rank_psps(tx)
        primary   = ranked[0]
        fallbacks = ranked[1:]

        # 4. Volume guardrail — if primary is over-concentrated, nudge to next
        primary = self._apply_guardrail(primary, fallbacks)

        # 5. Cron-specific overrides
        notes: list[str] = []
        if tx.is_cron:
            notes.append("Cron batch — avoiding psp-e (low cron AR: 29-35%).")
            primary, fallbacks = self._cron_override(primary, fallbacks)

        ar = self._expected_ar(tx.issuer, primary)
        cost = PSP_FEES[primary]

        # 6. Critically-low issuer warning
        if tx.issuer in ("bradescard", "liverpool"):
            notes.append(
                f"Issuer '{tx.issuer}' has critically low baseline AR (<26%). "
                "Consider alternative collection channel before card retry."
            )
            max_attempts = min(max_attempts, 2)

        return RoutingDecision(
            recommended_psp   = primary,
            fallback_psps     = fallbacks,
            retry             = True,
            retry_on_psp      = fallbacks[0] if fallbacks else primary,
            max_attempts      = max_attempts,
            stop_reason       = None,
            expected_cost_pct = cost,
            expected_ar       = ar,
            notes             = notes,
        )

    # ── private helpers ─────────────────────────────────────────────────────

    def _is_hard_decline(self, msg: str) -> bool:
        return any(pattern in msg for pattern in HARD_DECLINE_PATTERNS)

    def _max_attempts_policy(self, tx: Transaction) -> int:
        """
        Step 1 retry analysis: AR drops below 20% after attempt 6.
        Cron gets a shorter leash (AR degrades faster without user context).
        Critically-low issuers capped at 2.
        """
        if tx.issuer in ("bradescard", "liverpool"):
            return 2
        if tx.is_cron:
            return 3
        return 5

    def _rank_psps(self, tx: Transaction) -> list[str]:
        """
        Blend cost ranking and AR ranking according to self.knob.
        knob=0 → pure cost order; knob=1 → pure AR order.
        Returns ordered list of PSPs, best first.
        """
        issuer_key = tx.issuer if tx.issuer in ISSUER_PSP_AR else None

        def score(psp: str) -> float:
            # Cost score: invert fee so lower fee = higher score (0–1 range)
            min_fee, max_fee = min(PSP_FEES.values()), max(PSP_FEES.values())
            cost_score = 1 - (PSP_FEES[psp] - min_fee) / (max_fee - min_fee + 1e-9)

            # AR score: use issuer table if available; else use global AR proxy
            if issuer_key and psp in ISSUER_PSP_AR[issuer_key]:
                ar_score = ISSUER_PSP_AR[issuer_key][psp]
            elif psp in BIN_AWARE_PSPS:
                # psp-c global ~73%, psp-e global ~56%
                ar_score = 0.734 if psp == "psp-c" else 0.558
            else:
                # psp-o and psp-d have no BIN signal — assign generic AR
                ar_score = 0.498 if psp == "psp-o" else 0.330

            return (1 - self.knob) * cost_score + self.knob * ar_score

        return sorted(PSP_FEES.keys(), key=score, reverse=True)

    def _apply_guardrail(self, primary: str, fallbacks: list[str]) -> str:
        """
        If the primary PSP is already receiving more than (1 - guardrail) of
        traffic, rotate to the next best option to maintain diversity.
        """
        cap = 1.0 - self.volume_guardrail
        if self._traffic_share.get(primary, 0) > cap and fallbacks:
            return fallbacks[0]
        return primary

    def _cron_override(
        self, primary: str, fallbacks: list[str]
    ) -> tuple[str, list[str]]:
        """
        For cron: psp-e performs poorly (Cut 4: 29-36% AR on cron).
        Prefer psp-c → psp-o → psp-d; push psp-e to last resort.
        """
        order = [p for p in ["psp-c", "psp-o", "psp-d", "psp-e"]
                 if p in [primary] + fallbacks]
        if not order:
            return primary, fallbacks
        return order[0], order[1:]

    def _expected_ar(self, issuer: Optional[str], psp: str) -> Optional[float]:
        if issuer and issuer in ISSUER_PSP_AR:
            return ISSUER_PSP_AR[issuer].get(psp)
        return None

    def expected_cost(self, amount: float, psp: str) -> float:
        """Fee in currency units for an approved transaction."""
        return amount * PSP_FEES[psp]


# ─────────────────────────────────────────────────────────────────────────────
# DEMONSTRATION
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    def run_case(label: str, tx: Transaction, knob: float = 0.5):
        orch = PaymentOrchestrator(knob=knob, volume_guardrail=0.10)
        decision = orch.route(tx)
        cost_mxn = orch.expected_cost(tx.amount, decision.recommended_psp) \
                   if decision.recommended_psp != "none" else 0.0
        print(f"\n{'─'*60}")
        print(f"CASE: {label}  [knob={knob}]")
        print(f"  amount: ${tx.amount:,.2f} MXN | issuer: {tx.issuer or '—'} "
              f"| cron: {tx.is_cron} | attempt: #{tx.attempt_number}")
        if tx.error_message:
            print(f"  error_message: {tx.error_message}")
        print("  → Decision:")
        decision.display()
        if decision.recommended_psp != "none":
            print(f"  fee on approval  : ${cost_mxn:.2f} MXN")

    # ── Case 1: Nu MX — knob=1.0 (max acceptance) ───────────────────────────
    run_case(
        label = "Nu MX — high-value installment, optimise for acceptance",
        tx    = Transaction(amount=1_450.00, issuer="Nu MX",
                            funding_type="debit", gateway="checkout"),
        knob  = 1.0,
    )

    # ── Case 2: Cron batch — Bancoppel, overnight auto-collection ────────────
    run_case(
        label = "Cron batch — Bancoppel debit, overnight auto-collection",
        tx    = Transaction(amount=380.00, issuer="Bancoppel",
                            funding_type="debit", gateway="cron",
                            is_cron=True, attempt_number=2),
        knob  = 0.5,
    )

    # ── Case 3: Hard decline — insufficient funds on retry ───────────────────
    run_case(
        label = "Hard decline — BBVA insufficient funds on 3rd attempt",
        tx    = Transaction(amount=620.00, issuer="BBVA",
                            funding_type="credit", gateway="user-dashboard-nextpayment",
                            error_message="The card doesn't have sufficient funds",
                            attempt_number=3),
        knob  = 0.5,
    )

    # ── Case 4: Banco Mercantil del Norte — knob=1.0 ─────────────────────────
    run_case(
        label = "Banco Mercantil del Norte — psp-e should win on acceptance",
        tx    = Transaction(amount=870.00, issuer="Banco Mercantil del Norte",
                            funding_type="debit", gateway="nextpayment"),
        knob  = 1.0,
    )

    print(f"\n{'─'*60}")
    print("BONUS: same Banco Mercantil del Norte tx at knob=0.0 (min cost)")
    run_case(
        label = "Banco Mercantil del Norte — knob=0.0 → cost wins over AR",
        tx    = Transaction(amount=870.00, issuer="Banco Mercantil del Norte",
                            funding_type="debit", gateway="nextpayment"),
        knob  = 0.0,
    )
