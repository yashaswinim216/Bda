"""Shared domain constants and small helper utilities.

These values are used by the generator, the validator, the importer and the
analytics module so that the same business rules exist in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Dataset schema (20 columns, one row = one e-commerce order)
# --------------------------------------------------------------------------

REQUIRED_COLUMNS: list[str] = [
    "order_id",
    "customer_id",
    "customer_name",
    "age",
    "gender",
    "city",
    "state",
    "product_id",
    "product_name",
    "category",
    "subcategory",
    "quantity",
    "unit_price",
    "discount",
    "payment_method",
    "order_date",
    "delivery_days",
    "order_status",
    "rating",
    "total_amount",
]

# --------------------------------------------------------------------------
# Allowed categorical values
# --------------------------------------------------------------------------

VALID_CATEGORIES: list[str] = [
    "Electronics",
    "Clothing",
    "Furniture",
    "Groceries",
    "Beauty",
    "Sports",
    "Books",
    "Home Appliances",
]

VALID_ORDER_STATUSES: list[str] = [
    "Delivered",
    "Shipped",
    "Processing",
    "Cancelled",
    "Returned",
]

VALID_PAYMENT_METHODS: list[str] = [
    "UPI",
    "Credit Card",
    "Debit Card",
    "Net Banking",
    "Cash on Delivery",
    "Wallet",
]

VALID_GENDERS: list[str] = ["Male", "Female", "Other"]

# --------------------------------------------------------------------------
# Indian states and their major cities (used for realistic address data)
# --------------------------------------------------------------------------

INDIAN_LOCATIONS: dict[str, list[str]] = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Thane", "Nashik"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru"],
    "Delhi": ["New Delhi", "Dwarka", "Rohini", "Saket"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Noida", "Agra"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Salem"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Siliguri"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
    "Telangana": ["Hyderabad", "Warangal", "Secunderabad"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
    "Kerala": ["Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior"],
    "Punjab": ["Ludhiana", "Amritsar", "Patiala", "Jalandhar"],
    "Bihar": ["Patna", "Gaya", "Muzaffarpur"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Haldwani"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur"],
    "Goa": ["Panaji", "Margao", "Vasco da Gama"],
}

# Cities grouped by state - convenient for weighted random choices.
CITY_STATE_PAIRS: list[tuple[str, str]] = [
    (city, state) for state, cities in INDIAN_LOCATIONS.items() for city in cities
]


def project_root() -> Path:
    """Return the project root directory (the folder that contains ``src``)."""
    return Path(__file__).resolve().parents[1]


def human_filesize(num_bytes: float) -> str:
    """Format a byte count as a human readable string, e.g. ``14.05 MB``."""
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"
