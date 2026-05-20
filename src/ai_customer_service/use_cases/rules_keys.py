"""RulesKey — centralised constants for all BusinessRulesRepository keys.

Every key read or written via BusinessRulesRepository.get() / .set() must be
declared here.  This prevents typos, makes rename-refactoring safe, and gives
readers a single place to understand the full rule catalogue.

Usage::

    from ..use_cases.rules_keys import RulesKey

    rate = await rules_service.get(RulesKey.RUSH_FEE_STANDARD, 0.50)
    refund_key = RulesKey.refund_rate_key(stage.value)
"""
from __future__ import annotations


class RulesKey:
    # ── Rush fee rates (float: additional fraction of order total) ────────────
    RUSH_FEE_STANDARD = "rush_fee_rate.standard_rush"   # default 0.50  → +50 %
    RUSH_FEE_SUPER    = "rush_fee_rate.super_rush"       # default 1.00  → +100 %

    # ── Rush delivery windows (int: calendar days) ────────────────────────────
    RUSH_DAYS_STANDARD = "rush_days.standard_rush"       # default 30
    RUSH_DAYS_SUPER    = "rush_days.super_rush"          # default 15

    # ── Refund rates by production stage (float: 0.0–1.0) ────────────────────
    # These are stored as individual keys: refund_rate.<stage_value>
    # Use the helper below rather than building the key inline.
    _REFUND_RATE_PREFIX = "refund_rate"

    @staticmethod
    def refund_rate_key(stage_value: str) -> str:
        """Return the DB key for a stage's refund rate.

        Example::
            RulesKey.refund_rate_key("cutting")  → "refund_rate.cutting"
        """
        return f"refund_rate.{stage_value}"

    # ── SLA thresholds ────────────────────────────────────────────────────────
    SLA_HITL_MINUTES            = "sla_hitl_minutes"             # default 2
    SLA_HUMAN_RESPONSE_MINUTES  = "sla_human_response_minutes"   # default 5
    SLA_RESOLVE_HOURS           = "sla_resolve_hours"            # default 24

    # ── HITL / automation ────────────────────────────────────────────────────
    HITL_AUTO_TIMEOUT_MINUTES   = "hitl_auto_timeout_minutes"    # default 10
    HITL_REQUIRED_ACTIONS       = "hitl_required_actions"        # JSON list of action strings

    # ── Localisation ─────────────────────────────────────────────────────────
    DEFAULT_LANGUAGE = "default_language"                        # e.g. "zh-CN"
