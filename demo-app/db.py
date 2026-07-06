"""Database connection settings for the demo storefront."""
import os
DATABASE_URL = os.getenv("DATABASE_URL")


def connection_info() -> dict:
    """Connection parameters the app hands to its DB driver."""
    return {"url": DATABASE_URL, "pool_size": 5}
