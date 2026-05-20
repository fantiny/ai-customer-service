from __future__ import annotations

from datetime import date
from typing import Any

from ..domain.entities import Order, OrderActionRequest, OrderActionResult
from ..domain.exceptions import InvalidOrderActionError, OrderAccessDeniedError
from ..domain.value_objects import OrderStatus, ProductionStage, RushLevel
from .interfaces import IOrderRepository, IOrderService
from .rules_keys import RulesKey

# Refund rate by production stage when cancelling a custom order.
# These are FALLBACK values used only when DB rules are unreachable.
# Authoritative values live in business_rules (refund_rate.*) and must stay in sync.
_CUSTOM_REFUND_RATES: dict[ProductionStage, float] = {
    ProductionStage.PENDING:   1.00,  # 全额退款（未开始裁剪）
    ProductionStage.CONFIRMED: 1.00,  # 全额退款（已确认但未开始裁剪）
    ProductionStage.CUTTING:   0.70,  # 退70%（面料已裁剪）
    ProductionStage.SEWING:    0.30,  # 退30%（缝制中，人工成本已发生）
    ProductionStage.BEADING:   0.00,  # 不退款（珠绣/后期工艺）
    ProductionStage.QC:        0.00,
    ProductionStage.READY:     0.00,
}

_STAGE_LABELS: dict[ProductionStage, str] = {
    ProductionStage.PENDING:   "待排产（预计 1-3 个工作日内确认）",
    ProductionStage.CONFIRMED: "已排产，即将开始面料准备",
    ProductionStage.CUTTING:   "面料剪裁中（约需 3-5 天）",
    ProductionStage.SEWING:    "主体缝制中（约需 10-15 天）",
    ProductionStage.BEADING:   "珠绣与装饰工艺中（约需 5-10 天）",
    ProductionStage.QC:        "质量检验中（约需 1-2 天）",
    ProductionStage.READY:     "制作完成，正在安排发货",
}

_RUSH_SURCHARGE: dict[str, float] = {
    RushLevel.STANDARD_RUSH: 0.50,
    RushLevel.SUPER_RUSH:    1.00,
}

_RUSH_DAYS: dict[str, int] = {
    RushLevel.STANDARD_RUSH: 30,
    RushLevel.SUPER_RUSH:    15,
}


class OrderService(IOrderService):
    """Wedding dress order business logic with stage-based rules.

    When rules_repo is provided, refund rates and HITL action lists are read
    from the database (Phase 7 dynamic config). Falls back to hardcoded defaults.
    """

    def __init__(self, repo: IOrderRepository, rules_repo: Any = None) -> None:
        self._repo = repo
        self._rules = rules_repo  # BusinessRulesRepository | None

    async def list_orders(self, user_id: str) -> list[Order]:
        """Return up to 10 recent orders for the given user."""
        return await self._repo.list_by_user(user_id)

    async def execute(self, request: OrderActionRequest, user_id: str) -> OrderActionResult:
        dispatch = {
            "get_status":             self._get_status,
            "get_production_progress": self._get_production_progress,
            "get_tracking":           self._get_tracking,
            "get_refund_status":      self._get_refund_status,
            "cancel_order":           self._cancel_order,
            "initiate_refund":        self._initiate_refund,
            "request_rush":           self._request_rush,
            "exchange_order":         self._exchange_order,
        }
        handler = dispatch.get(request.action)
        if handler is None:
            raise InvalidOrderActionError(request.action, "unknown")
        return await handler(request.order_id, user_id, request.extra)

    async def validate(self, request: OrderActionRequest, user_id: str) -> Order:
        """Pre-validate a write action without executing it.

        Raises the same exceptions as execute() if the action is not feasible,
        so callers can surface errors to the user BEFORE triggering HITL.
        Only checks domain constraints; does NOT mutate any data.

        Returns the fetched Order so callers can extract metadata (e.g. wedding_date)
        without a second DB round-trip.

        get_refund_status is a read-only query — no domain constraints to validate;
        the order is still fetched and returned for metadata access.
        """
        order = await self._repo.get_by_id(request.order_id)
        self._assert_owner(order, user_id)
        if request.action == "get_refund_status":
            return order
        validators: dict[str, Any] = {
            "cancel_order":    self._validate_cancel,
            "initiate_refund": self._validate_refund,
            "request_rush":    self._validate_rush,
            "exchange_order":  self._validate_exchange,
        }
        fn = validators.get(request.action)
        if fn is None:
            raise InvalidOrderActionError(request.action, "unknown")
        fn(order, request.extra)
        return order

    def _validate_cancel(self, order: Any, extra: dict) -> None:
        # Status-level guard: only PENDING and CONFIRMED can be cancelled.
        # This mirrors _cancel_order exactly so HITL approval never leads to a
        # post-approval failure.
        non_cancellable = (
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
            OrderStatus.REFUNDED,
            OrderStatus.REFUND_PENDING,
            OrderStatus.EXCHANGE_PENDING,  # already in exchange flow → cannot cancel
        )
        if order.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
            raise InvalidOrderActionError(
                "cancel_order",
                f"订单当前状态（{order.status.value}）无法取消。"
                + ("如需退款请走退款流程。" if order.status in non_cancellable else ""),
            )
        # Stage-level guard for custom orders: zero-refund stages cannot be cancelled.
        # Mirrors the refund_rate == 0.0 check in _cancel_order.
        if order.wedding_meta.is_custom:
            zero_refund_stages = (
                ProductionStage.BEADING,
                ProductionStage.QC,
                ProductionStage.READY,
            )
            if order.wedding_meta.production_stage in zero_refund_stages:
                stage_label = _STAGE_LABELS.get(
                    order.wedding_meta.production_stage,
                    order.wedding_meta.production_stage.value,
                )
                raise InvalidOrderActionError(
                    "cancel_order",
                    f"定制婚纱已进入「{stage_label}」阶段，主体已成型，"
                    "按照定制服务协议无法退款。如有特殊情况请联系专属顾问协商处理。",
                )

    def _validate_refund(self, order: Any, extra: dict) -> None:
        non_refundable = (OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.REFUND_PENDING)
        if order.status in non_refundable:
            raise InvalidOrderActionError(
                "initiate_refund",
                f"订单当前状态（{order.status.value}）不支持退款申请。",
            )

    def _validate_exchange(self, order: Any, extra: dict) -> None:
        non_exchangeable = (OrderStatus.CANCELLED, OrderStatus.REFUNDED,
                            OrderStatus.REFUND_PENDING, OrderStatus.EXCHANGE_PENDING)
        if order.status in non_exchangeable:
            raise InvalidOrderActionError(
                "exchange_order",
                f"订单当前状态（{order.status.value}）不支持换货申请。",
            )
        if order.status not in (OrderStatus.DELIVERED,):
            raise InvalidOrderActionError(
                "exchange_order",
                "换货仅支持已签收的订单。如商品尚未送达，请等待签收后再申请。",
            )

    def _validate_rush(self, order: Any, extra: dict) -> None:
        if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED,
                            OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            raise InvalidOrderActionError(
                "request_rush",
                f"订单当前状态（{order.status.value}）不支持加急申请。",
            )
        if order.wedding_meta.production_stage in (ProductionStage.BEADING, ProductionStage.QC,
                                                   ProductionStage.READY):
            raise InvalidOrderActionError(
                "request_rush",
                "婚纱已进入后期制作阶段（珠绣/质检/完工），无法通过加急进一步缩短周期。"
                "如需紧急发货，请联系专属顾问安排优先出库。",
            )

    # ── Safe reads ──────────────────────────────────────────────────────────

    async def _get_status(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)

        status_labels = {
            OrderStatus.PENDING:       "待确认",
            OrderStatus.CONFIRMED:     "已确认",
            OrderStatus.SHIPPED:       "运输中",
            OrderStatus.DELIVERED:     "已送达",
            OrderStatus.CANCELLED:     "已取消",
            OrderStatus.REFUND_PENDING: "退款审核中",
            OrderStatus.REFUNDED:      "已退款",
        }
        meta = order.wedding_meta
        items_desc = "、".join(f"{i.name} ×{i.quantity}" for i in order.items)
        custom_hint = (
            f"\n- 定制款式：{meta.dress_style or '未记录'}"
            f"\n- 颜色：{meta.color}"
        ) if meta.is_custom else ""
        rush_hint = f"\n- 加急等级：{meta.rush_level.value}" if meta.is_rush else ""
        wedding_hint = f"\n- 婚礼日期：{meta.wedding_date}" if meta.wedding_date else ""

        return OrderActionResult(
            message=(
                f"💐 **订单 {order_id} 状态：{status_labels.get(order.status, order.status.value)}**\n"
                f"- 商品：{items_desc}\n"
                f"- 订单金额：¥{order.total:,.2f}"
                f"{custom_hint}{rush_hint}{wedding_hint}"
            ),
            order=order,
        )

    async def _get_production_progress(
        self, order_id: str, user_id: str, extra: dict
    ) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)
        meta = order.wedding_meta

        if not meta.is_custom:
            return OrderActionResult(
                message=(
                    f"订单 {order_id} 为现货商品，无定制生产进度。\n"
                    f"当前状态：**{order.status.value}**"
                ),
                order=order,
            )

        stage = meta.production_stage
        stage_label = _STAGE_LABELS.get(stage, stage.value)
        completion_hint = (
            f"\n预计完成日期：**{meta.estimated_completion}**"
            if meta.estimated_completion else ""
        )
        wedding_hint = (
            f"\n您的婚礼日期：{meta.wedding_date}，我们会确保准时交付 💕"
            if meta.wedding_date else ""
        )

        # Stage progress bar (visual)
        all_stages = list(ProductionStage)
        current_idx = all_stages.index(stage) if stage in all_stages else 0
        progress_bar = " → ".join(
            f"**[{s.value}]**" if i == current_idx else s.value
            for i, s in enumerate(all_stages)
        )

        return OrderActionResult(
            message=(
                f"🧵 **定制婚纱生产进度 — 订单 {order_id}**\n\n"
                f"当前阶段：**{stage_label}**\n\n"
                f"进度流程：{progress_bar}"
                f"{completion_hint}{wedding_hint}"
            ),
            order=order,
        )

    async def _get_tracking(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)
        if order.status not in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
            stage_hint = (
                f"当前生产阶段：{_STAGE_LABELS.get(order.wedding_meta.production_stage, '')}"
                if order.wedding_meta.is_custom else f"当前状态：{order.status.value}"
            )
            return OrderActionResult(
                message=f"订单 {order_id} 尚未发货。{stage_hint}",
                order=order,
            )
        tracking = order.tracking_number or "运单号待更新"
        return OrderActionResult(
            message=(
                f"📦 **订单 {order_id} 物流信息**\n"
                f"运单号：**{tracking}**\n"
                f"状态：{'已送达' if order.status == OrderStatus.DELIVERED else '运输中'}\n"
                "可在顺丰/EMS官网查询实时物流。"
            ),
            order=order,
        )

    # ── High-risk writes (called after HITL approval) ───────────────────────

    async def _get_refund_rate(self, stage: ProductionStage) -> float:
        """Return refund rate for a stage, preferring DB config over hardcoded defaults."""
        if self._rules:
            try:
                rate = await self._rules.get(RulesKey.refund_rate_key(stage.value))
                if rate is not None:
                    return float(rate)
            except Exception:
                pass
        return _CUSTOM_REFUND_RATES.get(stage, 0.0)

    async def _cancel_order(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)

        if order.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
            raise InvalidOrderActionError(
                "cancel_order",
                f"{order.status.value} 状态的订单无法取消",
            )

        meta = order.wedding_meta
        if meta.is_custom:
            stage = meta.production_stage
            refund_rate = await self._get_refund_rate(stage)
            refund_amount = order.total * refund_rate

            if refund_rate == 0.0:
                raise InvalidOrderActionError(
                    "cancel_order",
                    f"定制婚纱已进入「{_STAGE_LABELS.get(stage, stage.value)}」阶段，"
                    "主体已成型，按照定制服务协议无法退款。"
                    "如有特殊情况请联系专属顾问协商处理。",
                )

            await self._repo.update_status(order_id, OrderStatus.CANCELLED)
            return OrderActionResult(
                message=(
                    f"💔 订单 {order_id} 取消申请已受理。\n\n"
                    f"由于婚纱处于**{_STAGE_LABELS.get(stage, stage.value)}**阶段，\n"
                    f"按定制服务协议，退款比例为 **{int(refund_rate * 100)}%**，\n"
                    f"退款金额：¥{refund_amount:,.2f}\n"
                    "款项将在 3-5 个工作日内原路退回。"
                ),
                order=order,
            )

        # Non-custom order: full refund
        updated = await self._repo.update_status(order_id, OrderStatus.CANCELLED)
        return OrderActionResult(
            message=(
                f"订单 {order_id} 已成功取消，全额 ¥{order.total:,.2f} 将在 3-5 个工作日内退回。"
            ),
            order=updated,
        )

    async def _initiate_refund(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)

        if order.status not in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
            raise InvalidOrderActionError(
                "initiate_refund",
                f"订单当前状态（{order.status.value}）不支持直接申请退款，"
                "请先申请取消订单。",
            )

        updated = await self._repo.update_status(order_id, OrderStatus.REFUND_PENDING)
        return OrderActionResult(
            message=(
                f"退款申请已提交（¥{order.total:,.2f}）。\n"
                "专属顾问将在 1 个工作日内审核，通过后 3-5 个工作日退回原支付账户。\n"
                "感谢您对缘梦婚纱的信任 💕"
            ),
            order=updated,
        )

    async def _request_rush(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)
        meta = order.wedding_meta

        if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED,
                            OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            raise InvalidOrderActionError(
                "request_rush",
                f"订单当前状态（{order.status.value}）不支持加急申请。",
            )

        # Only allow rush upgrade when in early production
        if meta.production_stage in (ProductionStage.BEADING, ProductionStage.QC,
                                     ProductionStage.READY):
            raise InvalidOrderActionError(
                "request_rush",
                "婚纱已进入后期制作阶段，无法通过加急进一步缩短周期。",
            )

        rush_level = extra.get("rush_level") or RushLevel.STANDARD_RUSH
        surcharge_rate = _RUSH_SURCHARGE.get(rush_level, 0.5)
        surcharge = order.total * surcharge_rate
        delivery_days = _RUSH_DAYS.get(rush_level, 30)
        level_label = "特急" if rush_level == RushLevel.SUPER_RUSH else "加急"

        # Calculate estimated completion — use domain helper (already validated)
        completion_hint = ""
        wedding_dt = meta.wedding_date_as_date()
        if wedding_dt:
            days_remaining = (wedding_dt - date.today()).days
            completion_hint = (
                f"\n您的婚礼距今 **{days_remaining}** 天，"
                f"{level_label}后预计 {delivery_days} 天内交付，请确认时间充裕。"
            )

        return OrderActionResult(
            message=(
                f"🚀 **{level_label}申请已受理 — 订单 {order_id}**\n\n"
                f"{level_label}交期：{delivery_days} 天内\n"
                f"{level_label}附加费：¥{surcharge:,.2f}（原价 {int(surcharge_rate * 100)}%）\n"
                f"专属顾问将在 2 小时内与您确认产能并安排付款。"
                f"{completion_hint}"
            ),
            order=order,
        )

    async def _get_refund_status(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)

        status_map = {
            OrderStatus.REFUND_PENDING: (
                "🕐 **退款审核中**\n"
                f"您的订单 {order_id} 退款申请正在审核，预计 1 个工作日内处理完毕。\n"
                "审核通过后，款项将在 3-5 个工作日内退回原支付账户。"
            ),
            OrderStatus.REFUNDED: (
                "✅ **退款已完成**\n"
                f"订单 {order_id} 的退款（¥{order.total:,.2f}）已退回原支付账户。\n"
                "若未收到，请检查支付宝/微信账单或联系银行确认。"
            ),
            OrderStatus.EXCHANGE_PENDING: (
                "🔄 **换货处理中**\n"
                f"订单 {order_id} 的换货申请已受理，客服正在安排。\n"
                "确认后我们会联系您寄回原件并安排发出新品。"
            ),
            OrderStatus.CANCELLED: (
                "❌ **订单已取消**\n"
                f"订单 {order_id} 已取消。若已付款，退款将在 3-5 个工作日内到账。"
            ),
        }
        msg = status_map.get(
            order.status,
            f"订单 {order_id} 当前状态为「{order.status.value}」，暂无退款/换货记录。\n"
            "如需申请退款或换货，请发起相应申请。",
        )
        return OrderActionResult(message=msg, order=order)

    async def _exchange_order(self, order_id: str, user_id: str, extra: dict) -> OrderActionResult:
        order = await self._repo.get_by_id(order_id)
        self._assert_owner(order, user_id)

        if order.status != OrderStatus.DELIVERED:
            raise InvalidOrderActionError(
                "exchange_order",
                "换货仅支持已签收的订单。",
            )

        reason = extra.get("reason", "")
        reason_hint = f"\n换货原因：{reason}" if reason else ""

        updated = await self._repo.update_status(order_id, OrderStatus.EXCHANGE_PENDING)
        return OrderActionResult(
            message=(
                f"🔄 **换货申请已提交 — 订单 {order_id}**{reason_hint}\n\n"
                "专属顾问将在 1 个工作日内审核，审核通过后会联系您安排：\n"
                "1. 寄回原件（运费由我方承担）\n"
                "2. 收到原件后 7 日内发出新品\n\n"
                "感谢您的耐心，我们会尽快处理 💕"
            ),
            order=updated,
        )

    @staticmethod
    def _assert_owner(order, user_id: str) -> None:
        if order.user_id != user_id:
            raise OrderAccessDeniedError(order.order_id, user_id)
