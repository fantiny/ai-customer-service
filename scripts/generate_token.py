#!/usr/bin/env python3
"""缘梦婚纱 · 开发测试 JWT Token 生成器

需要在 .env 中配置 JWT_SECRET。

用法：
    uv run python scripts/generate_token.py --user user_chen_fang --name "陈方"
    uv run python scripts/generate_token.py --user user_li_mei --expires 3600
    uv run python scripts/generate_token.py --list    # 打印所有测试用户的 token
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_customer_service.infrastructure.auth import create_token
from ai_customer_service.infrastructure.config import get_settings

# 与 seed_all.py 对应的测试用户
TEST_USERS = [
    ("user_chen_fang",  "陈方",   "chen.fang@example.com",  "WD-2025-0001 缝制中"),
    ("user_liu_xin",    "刘欣",   "liu.xin@example.com",    "WD-2025-0002 剪裁中"),
    ("user_zhang_hui",  "张慧",   "zhang.hui@example.com",  "WD-2025-0003 珠绣·加急"),
    ("user_wang_min",   "王敏",   "wang.min@example.com",   "WD-2025-0004 质检中"),
    ("user_zhao_lei",   "赵磊",   "zhao.lei@example.com",   "WD-2025-0005 完成待发"),
    ("user_li_mei",     "李梅",   "li.mei@example.com",     "WD-2025-0006 已发货"),
    ("user_huang_ting", "黄婷",   "huang.ting@example.com", "WD-2025-0007 已发货·婚期6天"),
    ("user_luo_jia",    "罗佳",   "luo.jia@example.com",   "WD-2025-0024 质量投诉"),
    ("user_wei_qing",   "魏青",   "wei.qing@example.com",   "WD-2025-0023 退款处理中"),
    ("user_gao_lu",     "高璐",   "gao.lu@example.com",     "WD-2025-0013 待排产"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成测试 JWT")
    parser.add_argument("--user",    default="", help="用户 ID (sub claim)")
    parser.add_argument("--name",    default="", help="显示名称 (name claim)")
    parser.add_argument("--email",   default="", help="邮箱 (email claim)")
    parser.add_argument("--expires", type=int, default=86400, help="有效期（秒，默认24h）")
    parser.add_argument("--list",    action="store_true", help="打印所有测试用户 token")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.JWT_SECRET:
        print("❌  JWT_SECRET 未配置，请在 .env 中设置：")
        print("    JWT_SECRET=your-very-long-random-secret")
        sys.exit(1)

    if args.list:
        print(f"{'用户ID':20s} {'名称':8s} {'订单/场景':22s} Token URL")
        print("─" * 120)
        for uid, name, email, note in TEST_USERS:
            token = create_token(uid, name=name, email=email,
                                 expires_in=args.expires, settings=settings)
            url = f"http://localhost:3000/?token={token}"
            print(f"{uid:20s} {name:8s} {note:22s}")
            print(f"  {url[:100]}")
            print()
        return

    if not args.user:
        parser.print_help()
        sys.exit(1)

    token = create_token(
        args.user,
        name=args.name,
        email=args.email,
        expires_in=args.expires,
        settings=settings,
    )
    print(f"\n✅  Token for {args.user!r} (expires in {args.expires}s)\n")
    print(f"Bearer token:\n  {token}\n")
    print(f"Test URL:\n  http://localhost:3000/?token={token}\n")
    print(f"API test:\n  curl -H 'Authorization: Bearer {token}' http://localhost:8000/api/auth/me\n")


if __name__ == "__main__":
    main()
