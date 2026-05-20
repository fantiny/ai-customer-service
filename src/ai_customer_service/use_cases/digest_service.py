"""DigestService — daily operational KPI snapshot generator.

All SQL lives in DigestRepository (adapter layer).  This class contains
only pure Python KPI computation and Markdown formatting, making it fully
testable without a database connection.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from .interfaces import IDigestRepository

logger = logging.getLogger(__name__)


class DigestService:
    """Generates and stores daily operational KPI snapshots."""

    def __init__(self, repo: IDigestRepository) -> None:
        self._repo = repo

    async def generate(self, report_date: date | None = None) -> dict[str, Any]:
        """Compute metrics for *report_date* (default: yesterday) and upsert into daily_digests."""
        target = report_date or (date.today() - timedelta(days=1))
        day_start = datetime(target.year, target.month, target.day, 0, 0, 0)
        day_end = day_start + timedelta(days=1)

        # ── Fetch raw data from the repository ───────────────────────────────
        tickets = await self._repo.fetch_ticket_rows(day_start, day_end)
        msg_count = await self._repo.count_messages(day_start, day_end)
        open_count = await self._repo.count_open_tickets()

        # ── Pure KPI computation (no DB calls below) ──────────────────────────
        total = len(tickets)
        resolved = sum(1 for t in tickets if t["status"] in ("resolved", "closed"))
        escalated = sum(1 for t in tickets if t["assigned_agent_id"])
        ai_resolved = sum(
            1 for t in tickets
            if t["status"] in ("resolved", "closed") and not t["assigned_agent_id"]
        )

        resolve_times: list[float] = []
        for t in tickets:
            if t["resolved_at"] and t["created_at"]:
                delta = (t["resolved_at"] - t["created_at"]).total_seconds() / 60
                resolve_times.append(delta)
        avg_resolve = round(sum(resolve_times) / len(resolve_times), 1) if resolve_times else None

        ratings = [t["rating"] for t in tickets if t["rating"] is not None]
        csat_avg = round(sum(ratings) / len(ratings), 2) if ratings else None
        csat_dist = {str(i): ratings.count(i) for i in range(1, 6)}

        resolution_types: dict[str, int] = {}
        for t in tickets:
            rt = t["report_resolution_type"] or "unknown"
            resolution_types[rt] = resolution_types.get(rt, 0) + 1

        sentiment_counts: dict[str, int] = {}
        for t in tickets:
            s = t["report_sentiment_start"] or "unknown"
            sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

        ai_quality: dict[str, int] = {}
        for t in tickets:
            q = t["report_ai_quality"] or "unknown"
            ai_quality[q] = ai_quality.get(q, 0) + 1

        metrics: dict[str, Any] = {
            "date": target.isoformat(),
            "sessions": {
                "total": total,
                "ai_resolved": ai_resolved,
                "escalated_to_human": escalated,
                "resolved": resolved,
                "resolution_rate": round(resolved / total, 3) if total else 0,
                "avg_resolve_min": avg_resolve,
            },
            "messages": {"total": msg_count},
            "csat": {
                "avg_rating": csat_avg,
                "sample_count": len(ratings),
                "distribution": csat_dist,
            },
            "resolution_types": resolution_types,
            "sentiment_at_start": sentiment_counts,
            "ai_quality": ai_quality,
            "open_tickets_now": open_count,
        }

        # ── Persist ───────────────────────────────────────────────────────────
        digest_id = f"digest-{target.isoformat()}"
        await self._repo.save(digest_id, target, json.dumps(metrics), self._format_markdown(metrics))

        logger.info("Daily digest generated for %s: %d sessions", target, total)
        return metrics

    async def get(self, report_date: date) -> dict[str, Any] | None:
        """Retrieve a stored digest by date. Returns None if not found."""
        return await self._repo.get(report_date)

    async def list_recent(self, days: int = 7) -> list[dict[str, Any]]:
        """List the most recent *days* digest summaries."""
        return await self._repo.list_recent(days)

    # ── Internal formatting ───────────────────────────────────────────────────

    def _format_markdown(self, m: dict[str, Any]) -> str:
        s = m["sessions"]
        c = m["csat"]
        lines = [
            f"# 每日运营摘要 {m['date']}",
            "",
            "## 会话总览",
            f"- 总会话数：**{s['total']}**",
            f"- AI 自主解决：{s['ai_resolved']}（解决率 {s['resolution_rate']*100:.1f}%）",
            f"- 转人工：{s['escalated_to_human']}",
            (
                f"- 平均解决时长：{s['avg_resolve_min']} 分钟"
                if s["avg_resolve_min"] is not None
                else "- 平均解决时长：暂无数据"
            ),
            "",
            "## 客户满意度（CSAT）",
        ]
        if c["avg_rating"] is not None:
            dist = c["distribution"]
            lines.append(f"- 平均评分：**{c['avg_rating']}/5.0**（{c['sample_count']} 条）")
            lines.append(
                f"- 分布：⭐×{dist.get('1',0)} ⭐⭐×{dist.get('2',0)} "
                f"⭐⭐⭐×{dist.get('3',0)} ⭐⭐⭐⭐×{dist.get('4',0)} ⭐⭐⭐⭐⭐×{dist.get('5',0)}"
            )
        else:
            lines.append("- 暂无评分数据")
        lines += [
            "",
            f"## 当前待处理工单：{m['open_tickets_now']} 个",
        ]
        return "\n".join(lines)
