"""Bulk CSV import into MongoDB with PyMongo.

Reads the sales CSV in chunks, converts every row into a typed MongoDB
document and inserts the documents with ``bulk_write`` (never one insert
per document).

Usage
-----
    python src/import_data.py --file data/sales_data_100000.csv
    python src/import_data.py --file data/sales_data_100000.csv --batch-size 5000
    python src/import_data.py --file data/sales_data_100000.csv --drop

Duplicate protection
--------------------
A unique index on ``order_id`` is created before importing, so running the
same import twice skips rows that already exist instead of duplicating them.

Exit status: 0 success, 1 database error, 2 file/column problem.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from pymongo import InsertOne
from pymongo.collection import Collection
from pymongo.errors import BulkWriteError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src import database  # noqa: E402
from src.utils import REQUIRED_COLUMNS, project_root  # noqa: E402

DEFAULT_FILE = project_root() / "data" / "sales_data_100000.csv"
DEFAULT_BATCH_SIZE = 5000
UNIQUE_ORDER_INDEX = "ux_order_id"
DUPLICATE_KEY_CODE = 11000

TEXT_FIELDS = [
    "order_id",
    "customer_id",
    "customer_name",
    "gender",
    "city",
    "state",
    "product_id",
    "product_name",
    "category",
    "subcategory",
    "payment_method",
    "order_status",
]
INTEGER_FIELDS = ["age", "quantity", "delivery_days"]


def to_document(row: dict) -> Optional[dict]:
    """Convert one pandas row into a typed MongoDB document.

    Returns ``None`` when the row cannot be converted (bad date or number),
    so broken rows are counted as failures instead of crashing the import.
    """
    try:
        document: dict = {field: str(row[field]).strip() for field in TEXT_FIELDS}

        for field in INTEGER_FIELDS:
            document[field] = int(float(row[field]))
        document["discount"] = int(float(row["discount"]))

        unit_price = float(row["unit_price"])
        # Keep prices as integers when they are whole numbers (Indian rupees).
        if unit_price.is_integer():
            document["unit_price"] = int(unit_price)
        else:
            document["unit_price"] = unit_price
        document["total_amount"] = round(float(row["total_amount"]), 2)

        rating = row.get("rating")
        if rating is None or pd.isna(rating) or str(rating).strip() == "":
            document["rating"] = None
        else:
            document["rating"] = int(float(rating))

        order_date = row["order_date"]
        if isinstance(order_date, datetime):
            document["order_date"] = order_date
        else:
            document["order_date"] = datetime.strptime(str(order_date).strip(), "%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        return None
    return document


def ensure_unique_order_index(collection: Collection) -> None:
    """Create the unique ``order_id`` index used for duplicate protection."""
    names = [index["name"] for index in collection.list_indexes()]
    if UNIQUE_ORDER_INDEX in names:
        return
    try:
        collection.create_index("order_id", unique=True, name=UNIQUE_ORDER_INDEX)
    except Exception as exc:  # noqa: BLE001 - duplicate order_ids already stored
        raise RuntimeError(
            "Could not create the unique order_id index - the collection "
            "already contains duplicate order_id values.\n"
            "Re-run with --drop to rebuild the collection from the CSV.\n"
            f"Original error: {exc}"
        ) from exc


def import_csv(
    file_path: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    collection: Optional[Collection] = None,
    drop: bool = False,
    verbose: bool = True,
) -> dict:
    """Import ``file_path`` into the sales collection using bulk writes."""
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    started = time.perf_counter()
    stats: dict = {
        "file": str(file_path),
        "total": 0,
        "inserted": 0,
        "duplicates": 0,
        "failed": 0,
        "batch_size": batch_size,
        "duration_seconds": 0.0,
    }

    if collection is None:
        collection = database.get_collection(check=True)
    if drop:
        collection.drop()
        if verbose:
            print(f"Dropped collection '{collection.name}'.")

    ensure_unique_order_index(collection)

    batch_number = 0
    for chunk in pd.read_csv(file_path, chunksize=batch_size):
        missing = [column for column in REQUIRED_COLUMNS if column not in chunk.columns]
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(missing))

        rows = chunk.to_dict("records")
        documents: list[dict] = []
        for row in rows:
            document = to_document(row)
            if document is None:
                stats["failed"] += 1
            else:
                documents.append(document)
        stats["total"] += len(rows)

        if documents:
            try:
                result = collection.bulk_write(
                    [InsertOne(document) for document in documents], ordered=False
                )
                stats["inserted"] += result.inserted_count
            except BulkWriteError as exc:
                details = exc.details or {}
                stats["inserted"] += details.get("nInserted", 0)
                write_errors = details.get("writeErrors", [])
                duplicates = sum(
                    1 for error in write_errors if error.get("code") == DUPLICATE_KEY_CODE
                )
                stats["duplicates"] += duplicates
                stats["failed"] += len(write_errors) - duplicates

        batch_number += 1
        if verbose:
            print(
                f"  batch {batch_number}: processed {stats['total']:,} rows | "
                f"inserted {stats['inserted']:,} | duplicates {stats['duplicates']:,} | "
                f"failed {stats['failed']:,} | {time.perf_counter() - started:,.1f}s",
                flush=True,
            )

    stats["duration_seconds"] = round(time.perf_counter() - started, 2)
    return stats


def print_summary(stats: dict) -> None:
    """Print the import report."""
    duration = stats["duration_seconds"]
    processed = stats["inserted"] + stats["duplicates"] + stats["failed"]
    rate = processed / duration if duration > 0 else 0.0
    print("-" * 55)
    print("Import summary")
    print(f"  Source file  : {stats['file']}")
    print(f"  Database     : {config.get_database_name()}.{config.get_collection_name()}")
    print(f"  Total records: {stats['total']:,}")
    print(f"  Inserted     : {stats['inserted']:,}")
    print(f"  Duplicates   : {stats['duplicates']:,} (skipped, not re-inserted)")
    print(f"  Failed       : {stats['failed']:,}")
    print(f"  Batch size   : {stats['batch_size']:,}")
    print(f"  Duration     : {duration:.2f} seconds")
    print(f"  Throughput   : {rate:,.0f} records/second")
    print("-" * 55)
    if stats["total"] and stats["inserted"] == 0 and stats["failed"] == 0:
        print("Nothing new to insert - this dataset is already stored in MongoDB.")
    elif stats["failed"] == 0:
        print("Import finished successfully.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk import an e-commerce sales CSV into MongoDB."
    )
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_FILE, help="CSV file to import"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"documents per bulk write (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--drop", action="store_true", help="drop the collection before importing"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.file.exists():
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        return 2
    if args.batch_size <= 0:
        print("Error: --batch-size must be a positive integer.", file=sys.stderr)
        return 2

    if not database.is_mongodb_available():
        print(
            "Error: MongoDB is not reachable at "
            f"{config.redact_uri(config.get_mongo_uri())}.\n"
            "Start the MongoDB service and try again.",
            file=sys.stderr,
        )
        return 1

    print(f"Importing {args.file} into "
          f"{config.get_database_name()}.{config.get_collection_name()} ...")
    try:
        stats = import_csv(
            args.file, batch_size=args.batch_size, drop=args.drop, verbose=True
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_summary(stats)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
