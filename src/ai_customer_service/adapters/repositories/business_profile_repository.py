"""BusinessProfileRepository — loads BusinessProfile entities from the DB.

Reads from ``business_profiles`` (header row) and ``business_intents``
(per-intent rows) and assembles immutable ``BusinessProfile`` dataclass
instances for use in the graph layer.
"""
from __future__ import annotations

import asyncpg

from ...domain.entities import (
    BusinessProfile,
    ContactConfig,
    HandoffConfig,
    IntentDefinition,
    SafetyConfig,
    UrgencyConfig,
)
from ...use_cases.interfaces import IBusinessProfileRepository


class BusinessProfileRepository(IBusinessProfileRepository):
    """PostgreSQL implementation of IBusinessProfileRepository."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, business_id: str) -> BusinessProfile:
        """Load and assemble BusinessProfile from DB.

        Raises ValueError when the profile doesn't exist or is inactive.
        """
        async with self._pool.acquire() as conn:
            profile_row = await conn.fetchrow(
                """
                SELECT * FROM business_profiles
                WHERE business_id = $1 AND active = true
                """,
                business_id,
            )
            if profile_row is None:
                raise ValueError(
                    f"Business profile not found or inactive: {business_id!r}"
                )

            intent_rows = await conn.fetch(
                """
                SELECT * FROM business_intents
                WHERE business_id = $1 AND active = true
                ORDER BY sort_order, intent_id
                """,
                business_id,
            )

        # Deserialise JSONB fields (asyncpg returns dicts for JSONB columns)
        sc_raw: dict = profile_row["safety_config"] or {}
        uc_raw: dict = profile_row["urgency_config"] or {}
        cc_raw: dict = profile_row["contact_config"] or {}
        hc_raw: dict = profile_row["handoff_config"] or {}

        safety_config = SafetyConfig(
            escalation_keywords=tuple(sc_raw.get("escalation_keywords", [])),
            max_input_length=int(sc_raw.get("max_input_length", 2000)),
            escalation_thresholds=dict(sc_raw.get("escalation_thresholds", {})),
            urgent_escalation_threshold=int(sc_raw.get("urgent_escalation_threshold", 2)),
        )
        urgency_config = UrgencyConfig(
            enabled=bool(uc_raw.get("enabled", False)),
            deadline_field=str(uc_raw.get("deadline_field", "deadline_date")),
            urgent_days_threshold=int(uc_raw.get("urgent_days_threshold", 14)),
        )
        contact_config = ContactConfig(
            hotline=str(cc_raw.get("hotline", "")),
            website=str(cc_raw.get("website", "")),
            email=str(cc_raw.get("email", "")),
        )
        handoff_config = HandoffConfig(
            notify_customer=bool(hc_raw.get("notify_customer", True)),
            notification_template=str(
                hc_raw.get(
                    "notification_template",
                    "关于这个问题我帮您连线专属顾问，稍等一下～",
                )
            ),
            silent_handoff_message=str(hc_raw.get("silent_handoff_message", "")),
            handoff_language=hc_raw.get("handoff_language") or None,
        )

        intents = tuple(
            IntentDefinition(
                intent_id=r["intent_id"],
                display_name=r["display_name"],
                description=r["description"] or "",
                handler_node=r["handler_node"],
                requires_confirmation=bool(r["requires_confirmation"]),
                is_continuation_node=bool(r["is_continuation_node"]),
                negative_turns_threshold=r["negative_turns_threshold"],
            )
            for r in intent_rows
        )

        row_keys = set(profile_row.keys())
        return BusinessProfile(
            business_id=profile_row["business_id"],
            business_name=profile_row["business_name"],
            business_type=profile_row["business_type"],
            intents=intents,
            safety_config=safety_config,
            urgency_config=urgency_config,
            contact_config=contact_config,
            handoff_config=handoff_config,
            order_enabled=bool(profile_row["order_enabled"]),
            product_enabled=bool(profile_row["product_enabled"]),
            faq_enabled=bool(profile_row["faq_enabled"]),
            aftersales_enabled=bool(profile_row["aftersales_enabled"]),
            faq_category=str(profile_row["faq_category"]) if "faq_category" in row_keys and profile_row["faq_category"] else "wedding_dress_faq",
            product_catalog_category=str(profile_row["product_catalog_category"]) if "product_catalog_category" in row_keys and profile_row["product_catalog_category"] else "product_catalog",
            fallback_intent_id=profile_row["fallback_intent_id"],
        )
