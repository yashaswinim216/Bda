"""MongoDB aggregation analytics for the sales collection.

Every function here runs a **MongoDB aggregation pipeline** on the server -
the full collection is never loaded into Pandas just to add numbers up.

Common pipeline shape
---------------------
    1. ``$match``   - apply dashboard filters (category, state, dates, ...)
    2. ``$addFields`` - compute ``revenue = quantity * unit_price * (1 - discount/100)``
    3. ``$group``   - sum / average / count per key
    4. ``$sort`` / ``$limit`` - order results, keep the top/bottom N
    5. ``$project`` - rename fields and round revenue

All functions accept an optional ``filters`` dictionary::

    {"category": "Electronics", "state": "Karnataka",
     "date_from": "2026-01-01", "date_to": "2026-06-30",
     "city": "Bengaluru", "payment_method": "UPI",
     "order_status": "Delivered"}

Functions return plain Python numbers, lists of dictionaries or DataFrames,
so they can be used directly by the Streamlit dashboard. Every function
returns an empty/zero result when the collection (or the filter result)
is empty instead of raising an error.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional, Sequence, Union

import pandas as pd
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import database  # noqa: E402

DateLike = Union[str, date, datetime, None]

# Fields that can be filtered with an exact value (or a list of values).
FILTER_FIELDS = ("category", "state", "city", "payment_method", "order_status", "gender")

# revenue = quantity * unit_price * (1 - discount/100)
REVENUE_STAGE = {
    "$addFields": {
        "revenue": {
            "$multiply": [
                "$quantity",
                "$unit_price",
                {"$subtract": [1, {"$divide": ["$discount", 100]}]},
            ]
        }
    }
}

AGE_BRANCHES = [
    (25, "18-24"),
    (35, "25-34"),
    (45, "35-44"),
    (55, "45-54"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_collection() -> Collection:
    """Return the configured sales collection."""
    return database.get_collection()


def _to_datetime_start(value: DateLike) -> Optional[datetime]:
    """Convert a date-like value to a datetime at the start of the day."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def _to_datetime_end(value: DateLike) -> Optional[datetime]:
    """Convert a date-like value to the last instant of that day."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    parsed = _to_datetime_start(value)
    if parsed is not None:
        return datetime.combine(parsed.date(), time.max)
    return None


def build_match(filters: Optional[dict] = None) -> dict:
    """Translate the dashboard filter dictionary into a MongoDB ``$match``."""
    match: dict = {}
    if not filters:
        return match

    for field in FILTER_FIELDS:
        value = filters.get(field)
        if value in (None, "", [], ()):
            continue
        if isinstance(value, (list, tuple, set)):
            values = [item for item in value if item not in (None, "")]
            if values:
                match[field] = {"$in": list(values)}
        else:
            match[field] = value

    date_from = _to_datetime_start(filters.get("date_from"))
    date_to = _to_datetime_end(filters.get("date_to"))
    if date_from or date_to:
        date_match: dict = {}
        if date_from:
            date_match["$gte"] = date_from
        if date_to:
            date_match["$lte"] = date_to
        match["order_date"] = date_match
    return match


def _aggregate(collection: Collection, pipeline: Sequence[dict]) -> list[dict]:
    """Run an aggregation pipeline and return the resulting documents."""
    try:
        return list(collection.aggregate(list(pipeline), allowDiskUse=True))
    except PyMongoError as exc:
        raise RuntimeError(f"Aggregation failed: {exc}") from exc


def _base_pipeline(filters: Optional[dict] = None) -> list[dict]:
    """``$match`` (filters) followed by the ``revenue`` computed field."""
    return [{"$match": build_match(filters)}, REVENUE_STAGE]


def _group_by_field(
    field: str,
    filters: Optional[dict] = None,
    *,
    sort_by: str = "revenue",
    limit: Optional[int] = None,
    collection: Optional[Collection] = None,
) -> list[dict]:
    """Group revenue / quantity / orders by a single field."""
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": f"${field}",
                "revenue": {"$sum": "$revenue"},
                "quantity": {"$sum": "$quantity"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                field: "$_id",
                "revenue": {"$round": ["$revenue", 2]},
                "quantity": 1,
                "orders": 1,
            }
        },
        {"$sort": {sort_by: -1}},
    ]
    if limit:
        pipeline.append({"$limit": limit})
    return _aggregate(collection, pipeline)


def as_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Convert a list of result dictionaries into a DataFrame."""
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# KPI values
# ---------------------------------------------------------------------------

def get_total_revenue(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> float:
    """Sum of quantity x unit_price x (1 - discount/100) for all matching rows."""
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {"$group": {"_id": None, "revenue": {"$sum": "$revenue"}}}
    ]
    rows = _aggregate(collection, pipeline)
    return round(float(rows[0]["revenue"]), 2) if rows else 0.0


def get_total_orders(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> int:
    """Number of orders (documents) matching the filters."""
    collection = collection or get_collection()
    pipeline: list[dict] = [{"$match": build_match(filters)}, {"$count": "orders"}]
    rows = _aggregate(collection, pipeline)
    return int(rows[0]["orders"]) if rows else 0


def get_total_customers(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> int:
    """Number of distinct customers matching the filters."""
    collection = collection or get_collection()
    pipeline: list[dict] = [
        {"$match": build_match(filters)},
        {"$group": {"_id": "$customer_id"}},
        {"$count": "customers"},
    ]
    rows = _aggregate(collection, pipeline)
    return int(rows[0]["customers"]) if rows else 0


def get_total_products(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> int:
    """Number of distinct products matching the filters."""
    collection = collection or get_collection()
    pipeline: list[dict] = [
        {"$match": build_match(filters)},
        {"$group": {"_id": "$product_id"}},
        {"$count": "products"},
    ]
    rows = _aggregate(collection, pipeline)
    return int(rows[0]["products"]) if rows else 0


def get_total_quantity(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> int:
    """Total number of units sold."""
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {"$group": {"_id": None, "quantity": {"$sum": "$quantity"}}}
    ]
    rows = _aggregate(collection, pipeline)
    return int(rows[0]["quantity"]) if rows else 0


def get_average_order_value(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> float:
    """Average revenue per order (0.0 when there are no orders)."""
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": None,
                "revenue": {"$sum": "$revenue"},
                "orders": {"$sum": 1},
            }
        }
    ]
    rows = _aggregate(collection, pipeline)
    if not rows or not rows[0]["orders"]:
        return 0.0
    return round(rows[0]["revenue"] / rows[0]["orders"], 2)


def get_kpis(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> dict:
    """Return all dashboard KPI values in one dictionary."""
    return {
        "total_revenue": get_total_revenue(filters, collection),
        "total_orders": get_total_orders(filters, collection),
        "total_customers": get_total_customers(filters, collection),
        "total_products": get_total_products(filters, collection),
        "total_quantity": get_total_quantity(filters, collection),
        "average_order_value": get_average_order_value(filters, collection),
    }


# ---------------------------------------------------------------------------
# Sales breakdowns
# ---------------------------------------------------------------------------

def get_sales_by_category(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> list[dict]:
    """Revenue / quantity / orders grouped by category."""
    return _group_by_field("category", filters, collection=collection)


def get_sales_by_subcategory(
    filters: Optional[dict] = None,
    collection: Optional[Collection] = None,
    limit: Optional[int] = 20,
) -> list[dict]:
    """Revenue / quantity / orders grouped by subcategory."""
    return _group_by_field("subcategory", filters, collection=collection, limit=limit)


def get_sales_by_city(
    filters: Optional[dict] = None, collection: Optional[Collection] = None, limit: int = 15
) -> list[dict]:
    """Top cities by revenue."""
    return _group_by_field("city", filters, collection=collection, limit=limit)


def get_sales_by_state(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> list[dict]:
    """Revenue / quantity / orders grouped by state."""
    return _group_by_field("state", filters, collection=collection)


# ---------------------------------------------------------------------------
# Time based sales
# ---------------------------------------------------------------------------

def _sales_over_time(
    format_string: str,
    label: str,
    filters: Optional[dict] = None,
    collection: Optional[Collection] = None,
) -> list[dict]:
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": {"$dateToString": {"format": format_string, "date": "$order_date"}},
                "revenue": {"$sum": "$revenue"},
                "quantity": {"$sum": "$quantity"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                label: "$_id",
                "revenue": {"$round": ["$revenue", 2]},
                "quantity": 1,
                "orders": 1,
            }
        },
        {"$sort": {label: 1}},
    ]
    return _aggregate(collection, pipeline)


def get_daily_sales(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> list[dict]:
    """Revenue per calendar day (sorted oldest -> newest)."""
    return _sales_over_time("%Y-%m-%d", "date", filters, collection)


def get_monthly_sales(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> list[dict]:
    """Revenue per month (sorted oldest -> newest)."""
    return _sales_over_time("%Y-%m", "month", filters, collection)


def get_yearly_sales(filters: Optional[dict] = None, collection: Optional[Collection] = None) -> list[dict]:
    """Revenue per year (sorted oldest -> newest)."""
    return _sales_over_time("%Y", "year", filters, collection)


# ---------------------------------------------------------------------------
# Products and customers
# ---------------------------------------------------------------------------

def _top_products(
    filters: Optional[dict],
    collection: Optional[Collection],
    limit: int,
    ascending: bool,
) -> list[dict]:
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": "$product_id",
                "product_name": {"$first": "$product_name"},
                "category": {"$first": "$category"},
                "revenue": {"$sum": "$revenue"},
                "quantity": {"$sum": "$quantity"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "product_id": "$_id",
                "product_name": 1,
                "category": 1,
                "revenue": {"$round": ["$revenue", 2]},
                "quantity": 1,
                "orders": 1,
            }
        },
        {"$sort": {"revenue": 1 if ascending else -1}},
        {"$limit": limit},
    ]
    return _aggregate(collection, pipeline)


def get_top_products(
    filters: Optional[dict] = None,
    collection: Optional[Collection] = None,
    limit: int = 10,
) -> list[dict]:
    """Best products by revenue."""
    return _top_products(filters, collection, limit, ascending=False)


def get_bottom_products(
    filters: Optional[dict] = None,
    collection: Optional[Collection] = None,
    limit: int = 10,
) -> list[dict]:
    """Worst products by revenue."""
    return _top_products(filters, collection, limit, ascending=True)


def get_top_customers(
    filters: Optional[dict] = None,
    collection: Optional[Collection] = None,
    limit: int = 10,
) -> list[dict]:
    """Customers with the highest total spending."""
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": "$customer_id",
                "customer_name": {"$first": "$customer_name"},
                "city": {"$first": "$city"},
                "state": {"$first": "$state"},
                "revenue": {"$sum": "$revenue"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "customer_id": "$_id",
                "customer_name": 1,
                "city": 1,
                "state": 1,
                "revenue": {"$round": ["$revenue", 2]},
                "orders": 1,
            }
        },
        {"$sort": {"revenue": -1}},
        {"$limit": limit},
    ]
    return _aggregate(collection, pipeline)


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------

def _distribution(
    field: str,
    filters: Optional[dict],
    collection: Optional[Collection],
    sort_field: str,
) -> list[dict]:
    collection = collection or get_collection()
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": f"${field}",
                "revenue": {"$sum": "$revenue"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                field: "$_id",
                "revenue": {"$round": ["$revenue", 2]},
                "orders": 1,
            }
        },
        {"$sort": {sort_field: -1}},
    ]
    rows = _aggregate(collection, pipeline)
    total_orders = sum(row["orders"] for row in rows)
    for row in rows:
        row["percentage"] = (
            round(100.0 * row["orders"] / total_orders, 1) if total_orders else 0.0
        )
    return rows


def get_payment_method_distribution(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> list[dict]:
    """Order share and revenue for every payment method."""
    return _distribution("payment_method", filters, collection, sort_field="orders")


def get_order_status_distribution(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> list[dict]:
    """Order share and revenue for every order status."""
    return _distribution("order_status", filters, collection, sort_field="orders")


def get_sales_by_gender(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> list[dict]:
    """Revenue / orders grouped by gender."""
    return _distribution("gender", filters, collection, sort_field="orders")


def get_sales_by_age_group(
    filters: Optional[dict] = None, collection: Optional[Collection] = None
) -> list[dict]:
    """Revenue / orders grouped by customer age band."""
    collection = collection or get_collection()
    case_branches = [
        {"case": {"$lt": ["$age", upper]}, "then": label} for upper, label in AGE_BRANCHES
    ]
    pipeline = _base_pipeline(filters) + [
        {
            "$group": {
                "_id": {"$switch": {"branches": case_branches, "default": "55+"}},
                "revenue": {"$sum": "$revenue"},
                "orders": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "age_group": "$_id",
                "revenue": {"$round": ["$revenue", 2]},
                "orders": 1,
            }
        },
        {"$sort": {"age_group": 1}},
    ]
    rows = _aggregate(collection, pipeline)
    total_orders = sum(row["orders"] for row in rows)
    for row in rows:
        row["percentage"] = (
            round(100.0 * row["orders"] / total_orders, 1) if total_orders else 0.0
        )
    return rows
