"""WorkflowRepository — loads WorkflowDefinition entities from the DB.

Reads from ``business_workflows`` and assembles ``WorkflowDefinition``
dataclass instances including their structured ``WorkflowStep`` list.
"""
from __future__ import annotations

import asyncpg

from ...use_cases.interfaces import IWorkflowRepository, WorkflowDefinition, WorkflowStep


class WorkflowRepository(IWorkflowRepository):
    """PostgreSQL implementation of IWorkflowRepository."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_workflows(
        self,
        business_id: str,
        trigger_intent: str | None = None,
    ) -> list[WorkflowDefinition]:
        """Return active workflows for a business, optionally filtered by trigger intent."""
        async with self._pool.acquire() as conn:
            if trigger_intent is not None:
                rows = await conn.fetch(
                    """
                    SELECT * FROM business_workflows
                    WHERE business_id = $1
                      AND trigger_intent = $2
                      AND is_active = true
                    ORDER BY sort_order, workflow_id
                    """,
                    business_id,
                    trigger_intent,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM business_workflows
                    WHERE business_id = $1
                      AND is_active = true
                    ORDER BY sort_order, workflow_id
                    """,
                    business_id,
                )

        return [self._row_to_definition(r) for r in rows]

    async def get_workflow(
        self,
        workflow_id: str,
        business_id: str,
    ) -> WorkflowDefinition | None:
        """Return a specific workflow by ID, or None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM business_workflows
                WHERE workflow_id = $1 AND business_id = $2
                """,
                workflow_id,
                business_id,
            )

        if row is None:
            return None
        return self._row_to_definition(row)

    @staticmethod
    def _row_to_definition(row: asyncpg.Record) -> WorkflowDefinition:
        """Convert a DB row to a WorkflowDefinition dataclass."""
        # steps is stored as a JSONB array: [{step, instruction, action?, condition?}]
        raw_steps: list[dict] = row["steps"] or []
        steps = [
            WorkflowStep(
                step=int(s.get("step", i + 1)),
                instruction=str(s.get("instruction", "")),
                action=s.get("action") or None,
                condition=s.get("condition") or None,
            )
            for i, s in enumerate(raw_steps)
        ]
        return WorkflowDefinition(
            workflow_id=row["workflow_id"],
            business_id=row["business_id"],
            display_name=row["display_name"],
            trigger_intent=row["trigger_intent"],
            trigger_keywords=list(row["trigger_keywords"] or []),
            steps=steps,
            is_active=bool(row["is_active"]),
            sort_order=int(row["sort_order"]),
        )
