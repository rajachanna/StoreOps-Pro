"""Settings. Secrets and external Shopify connectivity are never on by default."""
from dataclasses import dataclass
from pathlib import Path
import os
import re

SHOP_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


@dataclass(frozen=True)
class Settings:
    database: Path = Path("data/storeops.sqlite")
    operator_key: str = ""
    shopify_secret: str = ""
    shop_domain: str = ""
    low_stock_threshold: int = 5
    high_value_cents: int = 100000

    @classmethod
    def from_env(cls):
        get = os.environ.get
        return cls(
            database=Path(get("STOREOPS_DB", "data/storeops.sqlite")),
            operator_key=get("STOREOPS_OPERATOR_KEY", ""),
            shopify_secret=get("STOREOPS_SHOPIFY_SECRET", ""),
            shop_domain=get("STOREOPS_SHOP_DOMAIN", ""),
            low_stock_threshold=int(get("STOREOPS_LOW_STOCK_THRESHOLD", "5")),
            high_value_cents=int(get("STOREOPS_HIGH_VALUE_CENTS", "100000")),
        )

    def validate(self):
        if self.low_stock_threshold < 0 or self.high_value_cents < 0:
            raise ValueError("Nonnegative risk thresholds required")
        if self.shop_domain and not SHOP_DOMAIN.fullmatch(self.shop_domain):
            raise ValueError("Shop domain must be a myshopify.com hostname")
        if self.shopify_secret and len(self.shopify_secret) < 16:
            raise ValueError("Shopify app secret too short")

    @property
    def operator_enabled(self):
        return len(self.operator_key) >= 24 and not self.operator_key.startswith("REPLACE_")

    @property
    def webhooks_enabled(self):
        return len(self.shopify_secret) >= 16 and bool(self.shop_domain)
