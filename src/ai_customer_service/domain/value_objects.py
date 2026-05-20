from enum import Enum


class Intent(str, Enum):
    PRODUCT = "product"
    FAQ = "faq"
    ORDER_READ = "order_read"
    ORDER_WRITE = "order_write"
    AFTERSALES = "aftersales"
    GENERAL = "general"
    BLOCKED = "blocked"


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    EXCHANGE_PENDING = "exchange_pending"


class ProductionStage(str, Enum):
    """Wedding dress custom order production lifecycle."""
    PENDING = "pending"        # 待排产
    CONFIRMED = "confirmed"    # 已排产，即将开始
    CUTTING = "cutting"        # 面料剪裁中
    SEWING = "sewing"          # 主体缝制中
    BEADING = "beading"        # 珠绣与装饰工艺中
    QC = "qc"                  # 质量检验中
    READY = "ready"            # 已完成，准备发货


class DressStyle(str, Enum):
    A_LINE = "a_line"          # A型/公主裙
    MERMAID = "mermaid"        # 鱼尾裙
    BALL_GOWN = "ball_gown"    # 蓬蓬裙/礼服裙
    SHEATH = "sheath"          # 修身款
    TEA_LENGTH = "tea_length"  # 中长款
    VINTAGE = "vintage"        # 复古款
    MINIMALIST = "minimalist"  # 简约款


class RushLevel(str, Enum):
    NONE = "none"                    # 标准周期（45-60天）
    STANDARD_RUSH = "standard_rush"  # 加急（30天，+50%附加费）
    SUPER_RUSH = "super_rush"        # 特急（15天，+100%附加费，视产能而定）


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
