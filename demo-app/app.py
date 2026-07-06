"""Demo storefront entry point (written by a coding agent)."""

import config
import db
from payments import PaymentClient


def create_app() -> dict:
    """Assemble the app's wiring: config, database, payments."""
    return {
        "api_base_url": config.API_BASE_URL,
        "debug": config.DEBUG,
        "db": db.connection_info(),
        "payments_client_cls": PaymentClient,
    }


if __name__ == "__main__":
    print(create_app())
