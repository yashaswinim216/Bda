"""Reusable PyMongo connection helpers.

All other modules obtain the collection through this module, so connection
logic and its error handling exist in exactly one place.

Usage
-----
    from src.database import get_collection, is_mongodb_available

    if not is_mongodb_available():
        print("MongoDB is not running")
    else:
        sales = get_collection()

Connection test
---------------
    python src/database.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    InvalidURI,
    ServerSelectionTimeoutError,
)

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402

# Cached client - opening a new connection for every query would be slow.
_client: Optional[MongoClient] = None
_client_uri: Optional[str] = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when MongoDB cannot be reached."""


def get_client(
    uri: Optional[str] = None,
    *,
    timeout_ms: Optional[int] = None,
    refresh: bool = False,
) -> MongoClient:
    """Return a (cached) MongoClient for ``uri``.

    Parameters
    ----------
    uri:
        Connection string; defaults to ``config.get_mongo_uri()``.
    timeout_ms:
        Server selection timeout in milliseconds.
    refresh:
        Drop the cached client and build a new one.
    """
    global _client, _client_uri

    uri = uri or config.get_mongo_uri()
    timeout_ms = timeout_ms or config.CONNECTION_TIMEOUT_MS

    if _client is not None and not refresh and _client_uri == uri:
        return _client

    try:
        client: MongoClient = MongoClient(
            uri,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
            appname="mongodb-bigdata-analytics",
        )
    except (InvalidURI, ConfigurationError) as exc:
        raise DatabaseUnavailableError(
            f"Invalid MongoDB connection settings: {exc}"
        ) from exc

    if _client is not None:
        _client.close()
    _client = client
    _client_uri = uri
    return client


def ping(uri: Optional[str] = None, *, timeout_ms: int = 2000) -> bool:
    """Return True when MongoDB answers a ping within ``timeout_ms``."""
    try:
        client = get_client(uri, timeout_ms=timeout_ms, refresh=uri is not None)
        client.admin.command("ping")
        return True
    except (
        ServerSelectionTimeoutError,
        ConnectionFailure,
        ConfigurationError,
        DatabaseUnavailableError,
        OSError,
    ):
        return False


def is_mongodb_available(uri: Optional[str] = None, *, timeout_ms: int = 2000) -> bool:
    """Alias of :func:`ping` with a clearer name for ``if`` conditions."""
    return ping(uri, timeout_ms=timeout_ms)


def require_database(uri: Optional[str] = None) -> None:
    """Raise :class:`DatabaseUnavailableError` with a helpful message."""
    if not ping(uri):
        raise DatabaseUnavailableError(
            "MongoDB is not reachable at "
            f"{config.redact_uri(uri or config.get_mongo_uri())}.\n"
            "  - Is the MongoDB service running? (Windows: services.msc -> MongoDB)\n"
            "  - Check MONGO_URI in your .env file."
        )


def get_database(name: Optional[str] = None, *, check: bool = False) -> Database:
    """Return the configured database (optionally verifying connectivity)."""
    if check:
        require_database()
    return get_client()[name or config.get_database_name()]


def get_collection(
    name: Optional[str] = None, *, check: bool = False
) -> Collection:
    """Return the configured collection (optionally verifying connectivity)."""
    return get_database(check=check)[name or config.get_collection_name()]


def connection_report(uri: Optional[str] = None) -> dict:
    """Collect connection details for the CLI test (credentials redacted)."""
    settings = config.describe_settings()
    report = {
        "uri": config.redact_uri(uri or config.get_mongo_uri()),
        "database": config.get_database_name(),
        "collection": config.get_collection_name(),
        "connected": False,
        "latency_ms": None,
        "server_version": None,
        "error": None,
    }
    started = time.perf_counter()
    try:
        client = get_client(uri, timeout_ms=2000, refresh=True)
        client.admin.command("ping")
        report["connected"] = True
        report["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        report["server_version"] = client.server_info().get("version")
    except Exception as exc:  # noqa: BLE001 - report any failure, hide credentials
        report["error"] = f"{type(exc).__name__}: {exc}"
    del settings
    return report


def close_connection() -> None:
    """Close the cached client (call this at the end of long scripts)."""
    global _client, _client_uri
    if _client is not None:
        _client.close()
    _client = None
    _client_uri = None


def main() -> int:
    """CLI: ``python src/database.py`` - simple connection test."""
    report = connection_report()
    print("MongoDB connection test")
    print("-" * 50)
    print(f"URI        : {report['uri']}")
    print(f"Database   : {report['database']}")
    print(f"Collection : {report['collection']}")
    if report["connected"]:
        print(f"Status     : OK - connected in {report['latency_ms']} ms")
        print(f"Server     : MongoDB {report['server_version']}")
        print("-" * 50)
        print("Connection successful.")
        return 0
    print("Status     : FAILED")
    print(f"Error      : {report['error']}")
    print("-" * 50)
    print(
        "MongoDB could not be reached.\n"
        "  - Start the MongoDB service (services.msc -> MongoDB)\n"
        "  - Verify MONGO_URI in .env (default: mongodb://localhost:27017/)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
