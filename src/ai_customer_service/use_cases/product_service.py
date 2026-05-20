from __future__ import annotations

from ..adapters.repositories.product_repository import ProductRepository
from ..domain.entities import ProductInfo
from .interfaces import IProductService


class ProductService(IProductService):
    """Concrete product service backed by the PostgreSQL product catalog."""

    def __init__(self, repo: ProductRepository) -> None:
        self._repo = repo

    async def list_all(self) -> list[ProductInfo]:
        return await self._repo.list_all()

    async def search(
        self,
        style: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        stock_type: str | None = None,
        rush_only: bool = False,
        limit: int = 20,
    ) -> list[ProductInfo]:
        return await self._repo.search(
            style=style,
            max_price=max_price,
            min_price=min_price,
            stock_type=stock_type,
            rush_only=rush_only,
            limit=limit,
        )

    async def get(self, product_id: str) -> ProductInfo | None:
        return await self._repo.get(product_id)
