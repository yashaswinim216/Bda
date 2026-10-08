"""Synthetic Indian e-commerce dataset generator.

Generates a CSV file of e-commerce transaction records. The default size is
100,000 records, but larger datasets (500,000 / 1,000,000) can be generated
for scalability testing:

    python src/generate_data.py --records 100000
    python src/generate_data.py --records 500000 --output data/sales_data_500000.csv

Notes
-----
* The official project dataset (``data/sales_data_100000.csv``) is supplied
  separately. This utility never overwrites an existing file unless
  ``--force`` is passed, so the official dataset cannot be replaced by
  accident.
* The data is synthetic (Faker + realistic catalogs). It does not represent
  real customers.
* Passing ``--seed`` makes the output deterministic (same seed = same CSV).
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

# Allow "python src/generate_data.py" as well as "from src.generate_data import ..."
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import (  # noqa: E402
    INDIAN_LOCATIONS,
    REQUIRED_COLUMNS,
    VALID_CATEGORIES,
    human_filesize,
    project_root,
)

DEFAULT_RECORDS = 100_000
DEFAULT_OUTPUT = project_root() / "data" / "sales_data_100000.csv"

# Inclusive date range for order dates.
DATE_START = date(2024, 1, 1)
DATE_END = date(2026, 9, 30)

# category -> subcategory -> (product name, min price, max price)
PRODUCT_CATALOG: dict[str, dict[str, list[tuple[str, int, int]]]] = {
    "Electronics": {
        "Mobiles": [("Smartphone", 8999, 79999), ("Feature Phone", 999, 2999)],
        "Audio": [
            ("Wireless Headphones", 999, 8999),
            ("Bluetooth Speaker", 799, 5999),
            ("Soundbar", 3999, 24999),
        ],
        "Computers": [
            ("Laptop", 28999, 129999),
            ("Wireless Mouse", 399, 1999),
            ("Mechanical Keyboard", 1499, 7999),
        ],
        "Cameras": [("Digital Camera", 15999, 64999), ("Webcam", 999, 5999)],
        "Accessories": [("Power Bank", 699, 3999), ("USB-C Cable", 149, 899)],
    },
    "Clothing": {
        "Men": [
            ("Cotton Shirt", 499, 1999),
            ("Denim Jeans", 799, 2999),
            ("T-Shirt", 299, 1299),
        ],
        "Women": [
            ("Kurta", 599, 2499),
            ("Leggings", 399, 1499),
            ("Saree", 999, 6999),
        ],
        "Footwear": [("Sneakers", 999, 4999), ("Formal Shoes", 1299, 5999)],
        "Kids": [("Kids T-Shirt", 249, 899), ("School Uniform", 349, 999)],
    },
    "Furniture": {
        "Living Room": [("Sofa", 12999, 49999), ("Recliner", 9999, 34999)],
        "Bedroom": [
            ("Bed with Mattress", 14999, 59999),
            ("Wardrobe", 8999, 29999),
        ],
        "Office": [("Office Desk", 4999, 19999), ("Ergonomic Chair", 5999, 24999)],
        "Decor": [("Bookshelf", 2999, 12999), ("Wall Clock", 399, 1999)],
    },
    "Groceries": {
        "Staples": [("Basmati Rice 5kg", 249, 699), ("Wheat Flour 5kg", 199, 499)],
        "Snacks": [("Namkeen Pack", 49, 249), ("Biscuits Combo", 99, 399)],
        "Beverages": [("Tea 500g", 199, 599), ("Instant Coffee", 249, 899)],
        "Fresh Produce": [("Fruits Basket", 199, 799), ("Vegetables Combo", 149, 599)],
    },
    "Beauty": {
        "Skincare": [("Face Wash", 149, 699), ("Sunscreen SPF 50", 349, 999)],
        "Haircare": [("Shampoo 650ml", 249, 799), ("Hair Oil", 149, 499)],
        "Makeup": [("Lipstick", 199, 1299), ("Foundation", 399, 1999)],
        "Fragrance": [("Perfume 100ml", 499, 3999)],
    },
    "Sports": {
        "Fitness": [("Yoga Mat", 399, 1999), ("Dumbbell Set", 999, 4999)],
        "Cricket": [("Cricket Bat", 1499, 9999), ("Cricket Ball Pack", 299, 999)],
        "Outdoor": [("Camping Tent", 2499, 12999), ("Trekking Backpack", 999, 4999)],
        "Cycling": [("Helmet", 799, 3999), ("Mountain Bike", 8999, 39999)],
    },
    "Books": {
        "Fiction": [("Novel", 199, 799)],
        "Academic": [("Engineering Textbook", 499, 1999)],
        "Children": [("Story Book", 149, 599)],
        "Competitive Exams": [("Exam Guide", 299, 1299)],
    },
    "Home Appliances": {
        "Kitchen": [
            ("Mixer Grinder", 1999, 8999),
            ("Microwave Oven", 4999, 19999),
            ("Induction Cooktop", 1299, 5999),
        ],
        "Cleaning": [
            ("Vacuum Cleaner", 3999, 18999),
            ("Washing Machine", 14999, 39999),
        ],
        "Climate": [("Air Cooler", 6999, 24999), ("Ceiling Fan", 1299, 4999)],
    },
}

# Weighted choices - big metros and popular options appear more often.
STATE_WEIGHTS = [18, 16, 14, 12, 10, 8, 8, 7, 6, 5, 4, 3, 3, 2, 2, 1, 1, 1, 1]
CATEGORIES = VALID_CATEGORIES
CATEGORY_WEIGHTS = [24, 22, 8, 14, 10, 8, 6, 8]

PAYMENT_METHODS = [
    "UPI",
    "Credit Card",
    "Debit Card",
    "Net Banking",
    "Cash on Delivery",
    "Wallet",
]
PAYMENT_WEIGHTS = [40, 18, 16, 14, 8, 4]

ORDER_STATUSES = ["Delivered", "Shipped", "Processing", "Cancelled", "Returned"]
STATUS_WEIGHTS = [62, 12, 10, 8, 8]

QUANTITIES = [1, 2, 3, 4, 5]
QUANTITY_WEIGHTS = [55, 25, 10, 6, 4]

DISCOUNTS = [0, 5, 10, 15, 20, 25, 30, 40, 50]
DISCOUNT_WEIGHTS = [22, 14, 22, 10, 14, 6, 6, 4, 2]

GENDERS = ["Male", "Female", "Other"]
GENDER_WEIGHTS = [52, 45, 3]


def build_products() -> list[tuple[str, str, str, str, int, int]]:
    """Flatten the catalog into rows of (product_id, category, subcategory,
    product_name, min_price, max_price). Order is deterministic."""
    products: list[tuple[str, str, str, str, int, int]] = []
    counter = 101
    for category in CATEGORIES:
        for subcategory, items in PRODUCT_CATALOG[category].items():
            for name, low, high in items:
                products.append((f"P{counter}", category, subcategory, name, low, high))
                counter += 1
    return products


def generate_customers(count: int, rng: random.Random, fake: Faker) -> list[dict]:
    """Create a reusable pool of customers (name / age / gender / city).

    Every customer stays in one city of one state, so an order's geography
    is always internally consistent.
    """
    customers: list[dict] = []
    for index in range(1, count + 1):
        state = rng.choices(_STATE_ORDER, weights=STATE_WEIGHTS, k=1)[0]
        cities = INDIAN_LOCATIONS[state]
        customers.append(
            {
                "customer_id": f"CUST{index:05d}",
                "customer_name": fake.name(),
                "age": rng.randint(18, 65),
                "gender": rng.choices(GENDERS, weights=GENDER_WEIGHTS, k=1)[0],
                "city": rng.choice(cities),
                "state": state,
            }
        )
    return customers


# Weighted list of states (weights mirror _STATE_ORDER, see STATE_WEIGHTS).
_STATE_ORDER = [
    "Maharashtra",
    "Karnataka",
    "Delhi",
    "Uttar Pradesh",
    "Tamil Nadu",
    "West Bengal",
    "Gujarat",
    "Telangana",
    "Rajasthan",
    "Kerala",
    "Madhya Pradesh",
    "Punjab",
    "Bihar",
    "Odisha",
    "Assam",
    "Uttarakhand",
    "Jharkhand",
    "Chhattisgarh",
    "Goa",
]


def generate_rows(
    records: int, customers: list[dict], rng: random.Random
) -> list[dict[str, object]]:
    """Build all order rows with realistic field relationships."""
    products = build_products()
    rows: list[dict[str, object]] = []
    span_days = (DATE_END - DATE_START).days

    for index in range(1, records + 1):
        customer = rng.choice(customers)
        product_id, category, subcategory, name, low, high = rng.choice(products)

        unit_price = rng.randint(low, high)
        quantity = rng.choices(QUANTITIES, weights=QUANTITY_WEIGHTS, k=1)[0]
        discount = rng.choices(DISCOUNTS, weights=DISCOUNT_WEIGHTS, k=1)[0]
        # total_amount must always reflect quantity x unit_price x discount
        total_amount = round(quantity * unit_price * (1 - discount / 100), 2)

        order_date = DATE_START + timedelta(days=rng.randint(0, span_days))
        status = rng.choices(ORDER_STATUSES, weights=STATUS_WEIGHTS, k=1)[0]

        rows.append(
            {
                "order_id": f"ORD{index:06d}",
                "customer_id": customer["customer_id"],
                "customer_name": customer["customer_name"],
                "age": customer["age"],
                "gender": customer["gender"],
                "city": customer["city"],
                "state": customer["state"],
                "product_id": product_id,
                "product_name": name,
                "category": category,
                "subcategory": subcategory,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount": discount,
                "payment_method": rng.choices(PAYMENT_METHODS, weights=PAYMENT_WEIGHTS, k=1)[0],
                "order_date": order_date.isoformat(),
                "delivery_days": rng.randint(1, 10),
                "order_status": status,
                "rating": rng.randint(1, 5),
                "total_amount": total_amount,
            }
        )
    return rows


def write_csv(rows: list[dict[str, object]], output: Path) -> None:
    """Write the generated rows to ``output`` using the canonical column order."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic Indian e-commerce sales dataset (CSV)."
    )
    parser.add_argument(
        "--records",
        type=int,
        default=DEFAULT_RECORDS,
        help=f"number of records to generate (default: {DEFAULT_RECORDS})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output CSV path (default: data/sales_data_100000.csv)",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="random seed for reproducible output"
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=5000,
        help="size of the reusable customer pool (default: 5000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.records <= 0:
        print("Error: --records must be a positive integer.", file=sys.stderr)
        return 2
    if args.output.exists() and not args.force:
        print(
            f"Error: {args.output} already exists.\n"
            "Refusing to overwrite an existing dataset. Use --force to replace it.",
            file=sys.stderr,
        )
        return 2

    rng = random.Random(args.seed)
    fake = Faker("en_IN")
    if args.seed is not None:
        Faker.seed(args.seed)

    print(f"Generating {args.records:,} records ...")
    started = time.perf_counter()
    customers = generate_customers(args.customers, rng, fake)
    rows = generate_rows(args.records, customers, rng)
    write_csv(rows, args.output)
    duration = time.perf_counter() - started

    size = args.output.stat().st_size
    print("\nDataset generation complete")
    print(f"  Records     : {args.records:,}")
    print(f"  Output path : {args.output}")
    print(f"  Duration    : {duration:.2f} seconds")
    print(f"  File size   : {human_filesize(size)}")
    if args.seed is not None:
        print(f"  Seed        : {args.seed} (deterministic output)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
