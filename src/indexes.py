"""MongoDB index management for the sales collection.

Indexes make filtering, sorting and grouping on indexed fields much faster,
but they also cost disk space and slow down inserts slightly, so only fields
that are actually used for filtering/sorting/aggregation are indexed.

Usage
-----
    python src/indexes.py            # create all indexes (idempotent)
    python src/indexes.py --list     # show current indexes
    python src/indexes.py --drop     # remove the project indexes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src import database  # noqa: E402

# Each entry: index name, key pattern, options, and why it exists.
INDEX_DEFINITIONS: list[dict] = [
    {
        "name": "ux_order_id",
        "keys": [("order_id", ASCENDING)],
        "options": {"unique": True},
        "reason": "one document per order + fast point lookups + duplicate protection",
    },
    {
        "name": "ix_customer_id",
        "keys": [("customer_id", ASCENDING)],
        "options": {},
        "reason": "orders of a single customer / top-customer analysis",
    },
    {
        "name": "ix_product_id",
        "keys": [("product_id", ASCENDING)],
        "options": {},
        "reason": "product-level lookups and product analytics",
    },
    {
        "name": "ix_category",
        "keys": [("category", ASCENDING)],
        "options": {},
        "reason": "category filters used by the dashboard",
    },
    {
        "name": "ix_state_city",
        "keys": [("state", ASCENDING), ("city", ASCENDING)],
        "options": {},
        "reason": "geographical filters (state, then city inside that state)",
    },
    {
        "name": "ix_order_date",
        "keys": [("order_date", DESCENDING)],
        "options": {},
        "reason": "date-range filters and newest-first sorting",
    },
    {
        "name": "ix_category_order_date",
        "keys": [("category", ASCENDING), ("order_date", DESCENDING)],
        "options": {},
        "reason": "category + date-range aggregations (monthly category trends)",
    },
    {
        "name": "ix_order_status_order_date",
        "keys": [("order_status", ASCENDING), ("order_date", DESCENDING)],
        "options": {},
        "reason": "order-status filters combined with date ranges",
    },
]

# Fields intentionally NOT indexed (explained in the README):
#   payment_method, order_status (alone), rating, gender, age
# These have very few distinct values, so MongoDB scans the collection anyway
# and an index would add write/storage cost without a real speed-up.

SYSTEM_INDEX = "_id_"


def create_indexes(collection: Collection, verbose: bool = True) -> list[str]:
    """Create every index from :data:`INDEX_DEFINITIONS` (idempotent)."""
    created: list[str] = []
    for definition in INDEX_DEFINITIONS:
        index_name = definition["name"]
        if index_name in [index["name"] for index in collection.list_indexes()]:
            if verbose:
                print(f"  = {index_name:<28} already exists")
            continue
        collection.create_index(
            definition["keys"], name=index_name, **definition["options"]
        )
        created.append(index_name)
        if verbose:
            print(f"  + {index_name:<28} created")
    return created


def drop_indexes(collection: Collection, verbose: bool = True) -> list[str]:
    """Remove all project indexes (the ``_id_`` index is never touched)."""
    dropped: list[str] = []
    for index in collection.list_indexes():
        name = index["name"]
        if name == SYSTEM_INDEX:
            continue
        collection.drop_index(name)
        dropped.append(name)
        if verbose:
            print(f"  - {name:<28} dropped")
    return dropped


def list_indexes(collection: Collection) -> list[dict]:
    """Return the current indexes as plain dictionaries."""
    return [dict(index) for index in collection.list_indexes()]


def index_size_bytes(collection: Collection) -> Optional[int]:
    """Return the total size of all indexes of the collection (bytes)."""
    try:
        stats = collection.database.command("collstats", collection.name)
        return int(stats.get("totalIndexSize", 0))
    except Exception:  # noqa: BLE001 - stats are informational only
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, list or drop the MongoDB indexes of the sales collection."
    )
    parser.add_argument("--list", action="store_true", help="list current indexes and exit")
    parser.add_argument("--drop", action="store_true", help="drop the project indexes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not database.is_mongodb_available():
        print(
            "Error: MongoDB is not reachable at "
            f"{config.redact_uri(config.get_mongo_uri())}.",
            file=sys.stderr,
        )
        return 1

    collection = database.get_collection()
    print(f"Indexes for {config.get_database_name()}.{collection.name}")
    print("-" * 60)

    if args.list:
        for index in list_indexes(collection):
            keys = ", ".join(f"{key}:{'desc' if order < 0 else 'asc'}"
                             for key, order in index.get("key", {}).items())
            unique = "unique" if index.get("unique") else ""
            print(f"  {index['name']:<30} ({keys}) {unique}")
        return 0

    size_before = index_size_bytes(collection)
    if args.drop:
        drop_indexes(collection)
        message = "dropped"
    else:
        create_indexes(collection)
        message = "ready"
    size_after = index_size_bytes(collection)

    print("-" * 60)
    if size_before is not None and size_after is not None:
        delta = size_after - size_before
        print(f"Index storage: {size_before:,} bytes -> {size_after:,} bytes "
              f"({delta:+,} bytes)")
    print(f"All indexes {message}.")
    if not args.drop:
        print("\nWhy these indexes exist:")
        for definition in INDEX_DEFINITIONS:
            print(f"  {definition['name']:<30} {definition['reason']}")
        print(
            "\nNot indexed on purpose: payment_method, rating, gender (few "
            "distinct values -> an index would not help much but would add "
            "write and storage cost)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
