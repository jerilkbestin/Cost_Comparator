from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class Variant(BaseModel):
    """A single product variant (e.g. Alloy Grey / XL)."""
    attributes: dict[str, str]   # e.g. {"colour": "Alloy Grey", "size": "XL"}
    price: float
    msrp: float | None = None
    in_stock: bool = True
    currency: str = "USD"

    @property
    def attr_key(self) -> str:
        """Stable string key used to match the same variant across snapshots."""
        return " / ".join(f"{k}:{v}" for k, v in sorted(self.attributes.items()))


class ProductSnapshot(BaseModel):
    """All variant prices captured at one point in time for a product."""
    product_name: str
    url: str
    variants: list[Variant]
    captured_at: datetime = None

    def model_post_init(self, __context):
        if self.captured_at is None:
            self.captured_at = datetime.utcnow()


class PriceDrop(BaseModel):
    """A single variant whose price dropped since last snapshot."""
    product_name: str
    url: str
    attributes: dict[str, str]
    old_price: float
    new_price: float
    currency: str

    @property
    def drop_pct(self) -> float:
        return round((self.old_price - self.new_price) / self.old_price * 100, 1)

    @property
    def attr_label(self) -> str:
        return " / ".join(v for v in self.attributes.values())
