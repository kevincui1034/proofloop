"""Payment processing for the demo storefront.

Wraps the Stripe API for charges and refunds. The secret key is read
from the environment when the client is constructed, so a missing key
fails fast at startup instead of at request time.
"""

import os
import uuid
from dataclasses import dataclass


def _load_api_key() -> str:
    return os.environ["STRIPE_API_KEY"]


@dataclass
class Charge:
    id: str
    amount_cents: int
    currency: str
    refunded: bool = False


class PaymentClient:
    """Minimal Stripe-like client used by the storefront."""

    def __init__(self) -> None:
        self._api_key = _load_api_key()
        self._charges: dict[str, Charge] = {}

    def create_charge(self, amount_cents: int, currency: str = "usd") -> Charge:
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        charge = Charge(
            id=f"ch_{uuid.uuid4().hex[:12]}",
            amount_cents=amount_cents,
            currency=currency,
        )
        self._charges[charge.id] = charge
        return charge

    def refund(self, charge_id: str) -> Charge:
        charge = self._charges[charge_id]
        charge.refunded = True
        return charge
