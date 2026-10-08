"""Environment-driven configuration for the project.

All settings come from environment variables (optionally loaded from a
``.env`` file next to ``requirements.txt``). Nothing is hard-coded in the
rest of the application, and credentials are never printed.

    MONGO_URI        default: mongodb://localhost:27017/
    MONGO_DATABASE   default: BigDataDB
    MONGO_COLLECTION default: sales
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = folder that contains requirements.txt / src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# Load .env once at import time. Missing file is not an error: the code
# simply falls back to the defaults below.
load_dotenv(ENV_FILE)

DEFAULT_MONGO_URI = "mongodb://localhost:27017/"
DEFAULT_DATABASE = "BigDataDB"
DEFAULT_COLLECTION = "sales"

# How long PyMongo waits for the server before giving up (milliseconds).
CONNECTION_TIMEOUT_MS = 5000


def _setting(name: str, default: str) -> str:
    """Read an environment variable, falling back to ``default``."""
    value = os.getenv(name, "").strip()
    return value or default


def get_mongo_uri() -> str:
    """Return the MongoDB connection URI (never logged with credentials)."""
    return _setting("MONGO_URI", DEFAULT_MONGO_URI)


def get_database_name() -> str:
    """Return the database name (default ``BigDataDB``)."""
    return _setting("MONGO_DATABASE", DEFAULT_DATABASE)


def get_collection_name() -> str:
    """Return the collection name (default ``sales``)."""
    return _setting("MONGO_COLLECTION", DEFAULT_COLLECTION)


def get_data_dir() -> Path:
    """Return the ``data/`` directory of the project."""
    return PROJECT_ROOT / "data"


def get_default_dataset_path() -> Path:
    """Return the path of the official 100,000 row dataset."""
    return get_data_dir() / "sales_data_100000.csv"


def redact_uri(uri: str) -> str:
    """Hide the username/password of a URI before it is printed or logged."""
    if "@" not in uri or "://" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    if ":" in credentials:
        user = credentials.split(":", 1)[0]
        credentials = f"{user}:****"
    else:
        credentials = f"{credentials}:****"
    return f"{scheme}://{credentials}@{host}"


def describe_settings() -> dict[str, str]:
    """Return the effective settings with the URI credentials hidden."""
    return {
        "uri": redact_uri(get_mongo_uri()),
        "database": get_database_name(),
        "collection": get_collection_name(),
        "env_file": str(ENV_FILE) if ENV_FILE.exists() else "(not found - using defaults)",
    }


def main() -> int:
    """Print the effective configuration (credentials redacted)."""
    print("Effective configuration")
    print("-" * 50)
    for key, value in describe_settings().items():
        print(f"{key:<12}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
