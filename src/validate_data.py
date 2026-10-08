"""Dataset validation pipeline.

Checks a sales CSV for structural and content problems before it is imported
into MongoDB:

* required columns
* missing values
* duplicate order IDs
* invalid quantities / prices / discounts / dates
* invalid categories / order statuses / payment methods / ratings / ages
* total_amount consistency (quantity x unit_price x discount)

Usage
-----
    python src/validate_data.py --file data/sales_data_100000.csv

Exit status
-----------
0  dataset passed all checks
1  dataset contains validation errors
2  file missing / unreadable / required columns missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import (  # noqa: E402
    REQUIRED_COLUMNS,
    VALID_CATEGORIES,
    VALID_GENDERS,
    VALID_ORDER_STATUSES,
    VALID_PAYMENT_METHODS,
    project_root,
)

DEFAULT_FILE = project_root() / "data" / "sales_data_100000.csv"

# Columns that must never be blank. ``rating`` is optional: only delivered
# orders carry a rating, so blank ratings are legitimate in this dataset.
REQUIRED_NON_NULL = [c for c in REQUIRED_COLUMNS if c != "rating"]

DATE_MIN = pd.Timestamp("2000-01-01")
DATE_MAX = pd.Timestamp("2100-12-31")


def _is_blank(series: pd.Series) -> pd.Series:
    """True where a cell is missing or only whitespace."""
    filled = series.fillna("").astype(str)
    return filled.str.strip() == ""


def _numeric(series: pd.Series) -> pd.Series:
    """Coerce to float; unparseable values become NaN."""
    return pd.to_numeric(series, errors="coerce")


def _not_integer(series: pd.Series) -> pd.Series:
    value = _numeric(series)
    return value.isna() | (value % 1 != 0)


def validate_dataset(path: str | Path) -> dict:
    """Validate a sales CSV and return a report dictionary.

    The report always contains ``status`` which is one of
    ``"passed"``, ``"failed"`` or ``"error"``.
    """
    path = Path(path)
    report: dict = {
        "file": str(path),
        "status": "error",
        "records_checked": 0,
        "errors": [],
    }

    if not path.exists():
        report["errors"].append(f"File not found: {path}")
        return report

    try:
        # Read every column as text so bad values are detected, not coerced.
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    except Exception as exc:  # noqa: BLE001 - report any parser problem clearly
        report["errors"].append(f"Could not read CSV: {exc}")
        return report

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        report["errors"].append(
            "Missing required columns: " + ", ".join(missing_columns)
        )
        report["found_columns"] = list(df.columns)
        return report

    total_rows = len(df)
    checks: dict[str, pd.Series] = {}

    # ---- missing values (in columns that must be filled) -----------------
    missing_mask = pd.Series(False, index=df.index)
    per_column_missing: dict[str, int] = {}
    for column in REQUIRED_NON_NULL:
        blank = _is_blank(df[column])
        per_column_missing[column] = int(blank.sum())
        missing_mask |= blank
    per_column_missing = {k: v for k, v in per_column_missing.items() if v}

    # ``rating`` is optional but must be 1-5 when present.
    rating_blank = _is_blank(df["rating"])

    # ---- duplicates -------------------------------------------------------
    duplicate_mask = df["order_id"].duplicated(keep=False) & ~_is_blank(df["order_id"])

    # ---- numeric checks ----------------------------------------------------
    quantity = _numeric(df["quantity"])
    checks["invalid_quantities"] = quantity.isna() | (quantity < 1) | (quantity % 1 != 0)

    price = _numeric(df["unit_price"])
    checks["invalid_prices"] = price.isna() | (price <= 0)

    discount = _numeric(df["discount"])
    checks["invalid_discounts"] = discount.isna() | (discount < 0) | (discount > 100)

    rating = _numeric(df["rating"])
    checks["invalid_ratings"] = (~rating_blank) & (
        rating.isna() | (rating % 1 != 0) | (rating < 1) | (rating > 5)
    )

    age = _numeric(df["age"])
    checks["invalid_ages"] = age.isna() | (age < 5) | (age > 120) | (age % 1 != 0)

    delivery = _numeric(df["delivery_days"])
    checks["invalid_delivery_days"] = (
        delivery.isna() | (delivery < 0) | (delivery > 60) | (delivery % 1 != 0)
    )

    # ---- date checks -------------------------------------------------------
    parsed_dates = pd.to_datetime(df["order_date"], errors="coerce", format="%Y-%m-%d")
    checks["invalid_dates"] = parsed_dates.isna() | (parsed_dates < DATE_MIN) | (
        parsed_dates > DATE_MAX
    )

    # ---- categorical checks ------------------------------------------------
    checks["invalid_categories"] = ~df["category"].isin(VALID_CATEGORIES)
    checks["invalid_order_statuses"] = ~df["order_status"].isin(VALID_ORDER_STATUSES)
    checks["invalid_payment_methods"] = ~df["payment_method"].isin(VALID_PAYMENT_METHODS)
    checks["invalid_genders"] = ~df["gender"].isin(VALID_GENDERS)

    # ---- total_amount consistency ------------------------------------------
    total = _numeric(df["total_amount"])
    expected = (quantity * price * (1 - discount / 100)).round(2)
    checks["invalid_total_amounts"] = total.isna() | (total <= 0)
    mismatch = (total - expected).abs() > 0.01
    # Only meaningful when the inputs themselves are valid numbers.
    mismatch = mismatch.fillna(False) & ~checks["invalid_prices"] & ~checks["invalid_quantities"]

    # ---- aggregate ---------------------------------------------------------
    invalid_rows = missing_mask | duplicate_mask | mismatch
    for mask in checks.values():
        invalid_rows |= mask.fillna(True)

    report.update(
        {
            "status": "passed" if int(invalid_rows.sum()) == 0 else "failed",
            "records_checked": total_rows,
            "columns_checked": len(REQUIRED_COLUMNS),
            "missing_values": int(missing_mask.sum()),
            "missing_values_by_column": per_column_missing,
            "blank_ratings": int(rating_blank.sum()),
            "duplicate_order_ids": int(df.loc[duplicate_mask, "order_id"].nunique()),
            "duplicate_rows": int(duplicate_mask.sum()),
            "total_amount_mismatches": int(mismatch.sum()),
            "invalid_records": int(invalid_rows.sum()),
            "checks": {name: int(mask.fillna(True).sum()) for name, mask in checks.items()},
        }
    )
    return report


def print_report(report: dict) -> None:
    """Print a human readable validation report."""
    print(f"Validation report: {report['file']}")
    print("-" * 60)

    if report["errors"]:
        for error in report["errors"]:
            print(f"ERROR: {error}")
        print("Result: ERROR")
        return

    checks = report["checks"]
    print(f"Records checked        : {report['records_checked']:,}")
    print(f"Columns checked        : {report['columns_checked']} / {len(REQUIRED_COLUMNS)}")
    print(f"Missing values         : {report['missing_values']:,}")
    if report["missing_values_by_column"]:
        for column, count in report["missing_values_by_column"].items():
            print(f"    - {column}: {count:,}")
    print(f"Blank ratings (allowed): {report['blank_ratings']:,}")
    print(f"Duplicate order IDs    : {report['duplicate_order_ids']:,}")
    labels = [
        ("invalid_quantities", "Invalid quantities"),
        ("invalid_prices", "Invalid prices"),
        ("invalid_discounts", "Invalid discounts"),
        ("invalid_dates", "Invalid dates"),
        ("invalid_categories", "Invalid categories"),
        ("invalid_order_statuses", "Invalid order statuses"),
        ("invalid_payment_methods", "Invalid payment methods"),
        ("invalid_ratings", "Invalid ratings"),
        ("invalid_ages", "Invalid ages"),
        ("invalid_delivery_days", "Invalid delivery days"),
        ("invalid_genders", "Invalid genders"),
        ("invalid_total_amounts", "Invalid total amounts"),
    ]
    for key, label in labels:
        print(f"{label:<22}: {checks[key]:,}")
    print(f"Total amount mismatches: {report['total_amount_mismatches']:,}")
    print(f"Invalid records        : {report['invalid_records']:,}")
    print("-" * 60)
    print(f"Result: {'PASSED' if report['status'] == 'passed' else 'FAILED'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an e-commerce sales CSV before importing it into MongoDB."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_FILE,
        help="path to the CSV file (default: data/sales_data_100000.csv)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat blank ratings as errors as well",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = validate_dataset(args.file)
    print_report(report)

    if report["status"] == "error":
        return 2
    if report["status"] == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
