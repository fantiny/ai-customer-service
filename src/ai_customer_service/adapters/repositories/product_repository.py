"""ProductRepository — structured product catalog queries.

All product data comes from the `products` table; the LLM never invents
product names, IDs, or prices.
"""
from __future__ import annotations

from typing import Optional

import asyncpg

from ...domain.entities import ProductInfo


class ProductRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_all(self) -> list[ProductInfo]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM products WHERE active=true ORDER BY price ASC"
            )
        return [self._row_to_product(r) for r in rows]

    async def search(
        self,
        style: Optional[str] = None,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        stock_type: Optional[str] = None,   # "ready" for in-stock only
        tags: Optional[list[str]] = None,
        rush_only: bool = False,
        limit: int = 5,
    ) -> list[ProductInfo]:
        conditions = ["active = true"]
        params: list = []
        i = 1
        if style:
            conditions.append(f"style = ${i}")
            params.append(style)
            i += 1
        if max_price is not None:
            conditions.append(f"price <= ${i}")
            params.append(max_price)
            i += 1
        if min_price is not None:
            conditions.append(f"price >= ${i}")
            params.append(min_price)
            i += 1
        if stock_type:
            conditions.append(f"stock_type = ${i}")
            params.append(stock_type)
            i += 1
        if rush_only:
            conditions.append("rush_available = true")
        if tags:
            conditions.append(f"tags && ${i}")
            params.append(tags)
            i += 1
        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM products WHERE {where} ORDER BY price ASC LIMIT {limit}",
                *params,
            )
        return [self._row_to_product(r) for r in rows]

    async def get(self, product_id: str) -> Optional[ProductInfo]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1 AND active = true",
                product_id,
            )
        return self._row_to_product(row) if row else None

    async def get_any(self, product_id: str) -> Optional[ProductInfo]:
        """Fetch product regardless of active status (for admin use)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1",
                product_id,
            )
        return self._row_to_product(row) if row else None

    async def list_all_admin(self) -> list[ProductInfo]:
        """Return all products including inactive (for admin management)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM products ORDER BY active DESC, price ASC"
            )
        return [self._row_to_product(r) for r in rows]

    async def update_product(self, product_id: str, updates: dict) -> Optional[ProductInfo]:
        """Update arbitrary product fields by name. Only whitelisted columns accepted."""
        allowed = {
            "name", "style", "price", "deposit_rate", "production_days",
            "rush_available", "stock_type", "colors", "tags", "description",
            "occasions", "active", "purchase_url",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return await self.get_any(product_id)
        set_clause = ", ".join(f"{col} = ${i+2}" for i, col in enumerate(filtered))
        values = list(filtered.values())
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE products SET {set_clause} WHERE product_id = $1 RETURNING *",
                product_id, *values,
            )
        return self._row_to_product(row) if row else None

    async def create_product(self, data: dict) -> ProductInfo:
        """Insert a new product row."""
        cols = [
            "product_id", "name", "style", "price", "deposit_rate", "production_days",
            "rush_available", "stock_type", "colors", "tags", "description",
            "occasions", "active", "purchase_url",
        ]
        vals = [data.get(c, "" if c in ("description", "purchase_url") else None) for c in cols]
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        col_list = ", ".join(cols)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"INSERT INTO products ({col_list}) VALUES ({placeholders}) RETURNING *",
                *vals,
            )
        return self._row_to_product(row)

    def _row_to_product(self, row: asyncpg.Record) -> ProductInfo:
        row_keys = set(row.keys())
        return ProductInfo(
            product_id=row["product_id"],
            name=row["name"],
            style=row["style"],
            price=float(row["price"]),
            deposit_rate=float(row["deposit_rate"]),
            production_days=row["production_days"],
            rush_available=row["rush_available"],
            stock_type=row["stock_type"],
            colors=list(row["colors"]),
            tags=list(row["tags"]),
            description=row["description"],
            occasions=list(row["occasions"]),
            active=row["active"],
            purchase_url=str(row["purchase_url"]) if "purchase_url" in row_keys and row["purchase_url"] else "",
        )
