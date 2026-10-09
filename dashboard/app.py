"""MongoDB Big Data Analytics Dashboard (Streamlit + Plotly).

Run with:

    streamlit run dashboard/app.py

The dashboard reuses ``src.database`` for the connection and
``src.analytics`` for every number it shows - no MongoDB logic is
duplicated here. All analytics are MongoDB aggregation pipelines, so only
result documents (never the full collection) reach the browser.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import analytics, config, database  # noqa: E402

st.set_page_config(
    page_title="MongoDB Big Data Analytics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

ACCENT = "#2563eb"
PALETTE = [
    "#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
    "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#64748b",
]

# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }
        h1, h2, h3 { font-family: "Segoe UI", sans-serif; letter-spacing: -0.01em; }
        section[data-testid="stSidebar"] { background-color: #f8fafc; }
        div[data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #e2e8f0;
            border-radius: 10px; padding: 14px 16px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
        }
        div[data-testid="stMetricLabel"] { color: #475569; font-size: 0.85rem; }
        div[data-testid="stMetricValue"] { font-weight: 600; color: #0f172a; }
        div[data-testid="stMetricDelta"] { font-size: 0.8rem; }
        .kpi-caption { color:#64748b; font-size:0.8rem; margin-top:-6px; }
        .section-note { color:#64748b; font-size:0.85rem; margin-bottom: 0.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Cached helpers (results are shared across reruns for 30 seconds)
# --------------------------------------------------------------------------
def _cache_key(filters: dict) -> tuple:
    """Turn the filter dictionary into a hashable cache key.

    Values keep their real types (lists become tuples) so that the cache
    key can be converted back into the original filter dictionary. Stringifying
    lists here would send ``"['Electronics']"`` to MongoDB instead of
    ``["Electronics"]`` and match nothing.
    """
    key: list[tuple] = []
    for name in sorted(filters):
        value = filters[name]
        if isinstance(value, (list, set)):
            value = tuple(sorted(str(item) for item in value))
        key.append((name, value))
    return tuple(key)


@st.cache_data(ttl=30, show_spinner=False)
def load_filter_options() -> dict:
    """Distinct values used by the sidebar filters + dataset date range."""
    collection = database.get_collection()
    pipeline = [
        {
            "$group": {
                "_id": None,
                "min_date": {"$min": "$order_date"},
                "max_date": {"$max": "$order_date"},
            }
        }
    ]
    bounds = list(collection.aggregate(pipeline))
    min_date = bounds[0]["min_date"].date() if bounds else date(2024, 1, 1)
    max_date = bounds[0]["max_date"].date() if bounds else date(2026, 12, 31)
    return {
        "categories": sorted(collection.distinct("category")),
        "states": sorted(collection.distinct("state")),
        "cities": sorted(collection.distinct("city")),
        "payment_methods": sorted(collection.distinct("payment_method")),
        "order_statuses": sorted(collection.distinct("order_status")),
        "min_date": min_date,
        "max_date": max_date,
        "document_count": collection.estimated_document_count(),
    }


@st.cache_data(ttl=30, show_spinner=False)
def run_query(function_name: str, filters: tuple) -> Any:
    """Run one named analytics function with the given filters (cached)."""
    # Rebuild the original dictionary: tuples go back to lists so that
    # ``build_match`` produces ``{field: {"$in": [...]}}`` again.
    filter_dict = {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in filters
    }
    function: Callable = getattr(analytics, function_name)
    return function(filter_dict)


def query(name: str, filters: dict) -> Any:
    """Cached wrapper that accepts the mutable filter dictionary."""
    return run_query(name, _cache_key(filters))


def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Result rows -> DataFrame (empty DataFrame keeps charts graceful)."""
    return pd.DataFrame(rows)


def money(value: float) -> str:
    """Format numbers as Indian rupees."""
    return f"₹{value:,.0f}"


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
def build_sidebar() -> dict:
    """Render the sidebar controls and return the active filter dictionary."""
    st.sidebar.title("📊 Analytics Filters")
    st.sidebar.caption(f"{config.get_database_name()}.{config.get_collection_name()}")

    if st.sidebar.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    options = st.session_state["filter_options"]

    # Widget state lives in session_state so that "Clear filters" can reset it.
    defaults = {
        "flt_date": (options["min_date"], options["max_date"]),
        "flt_category": [],
        "flt_state": [],
        "flt_city": [],
        "flt_payment": [],
        "flt_status": [],
    }
    for widget_key, default in defaults.items():
        st.session_state.setdefault(widget_key, default)

    date_range = st.sidebar.date_input("Order date range", key="flt_date")
    category = st.sidebar.multiselect(
        "Category", options["categories"], key="flt_category"
    )
    state = st.sidebar.multiselect("State", options["states"], key="flt_state")
    city = st.sidebar.multiselect("City", options["cities"], key="flt_city")
    payment_method = st.sidebar.multiselect(
        "Payment method", options["payment_methods"], key="flt_payment"
    )
    order_status = st.sidebar.multiselect(
        "Order status", options["order_statuses"], key="flt_status"
    )

    if st.sidebar.button("Clear filters", use_container_width=True):
        for widget_key in defaults:
            st.session_state.pop(widget_key, None)
        st.rerun()

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_from, date_to = date_range
    elif isinstance(date_range, tuple) and len(date_range) == 1:
        date_from = date_to = date_range[0]

    filters: dict = {
        "category": category,
        "state": state,
        "city": city,
        "payment_method": payment_method,
        "order_status": order_status,
    }
    # The date range only becomes a filter when it differs from the full range.
    full_range = (options["min_date"], options["max_date"])
    if (date_from, date_to) != full_range:
        filters["date_from"] = date_from.isoformat() if date_from else None
        filters["date_to"] = date_to.isoformat() if date_to else None

    # Drop empty filters so the $match stage stays clean.
    return {key: value for key, value in filters.items() if value}


def sidebar_status(connected: bool, server_version: Optional[str]) -> None:
    """Connection status at the bottom of the sidebar."""
    st.sidebar.markdown("---")
    if connected:
        st.sidebar.success(f"MongoDB connected (v{server_version})")
    else:
        st.sidebar.error("MongoDB unavailable")
    st.sidebar.caption(
        "Store → Process → Analyze → Visualize\n"
        "Synthetic e-commerce dataset (100,000 records)"
    )


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
def section(title: str, note: str = "") -> None:
    """Section heading with a short explanation."""
    st.markdown(f"### {title}")
    if note:
        st.markdown(f'<div class="section-note">{note}</div>', unsafe_allow_html=True)


def empty(message: str) -> None:
    """Consistent empty-state message for a chart section."""
    st.info(message)


def kpi_row(kpis: dict) -> None:
    """Six KPI cards in two rows of three."""
    first = st.columns(3)
    first[0].metric("Total Revenue", money(kpis["total_revenue"]))
    first[1].metric("Total Orders", f"{kpis['total_orders']:,}")
    first[2].metric("Total Customers", f"{kpis['total_customers']:,}")

    second = st.columns(3)
    second[0].metric("Average Order Value", money(kpis["average_order_value"]))
    second[1].metric("Total Products", f"{kpis['total_products']:,}")
    second[2].metric("Total Quantity Sold", f"{kpis['total_quantity']:,}")


def time_section(filters: dict) -> None:
    section(
        "Sales Over Time",
        "Monthly and daily revenue computed by MongoDB with $group + $dateToString.",
    )
    monthly = to_frame(query("get_monthly_sales", filters))
    daily = to_frame(query("get_daily_sales", filters))
    left, right = st.columns(2)

    with left:
        if monthly.empty:
            empty("No monthly sales for the current filters.")
        else:
            fig = px.line(
                monthly,
                x="month",
                y="revenue",
                markers=True,
                labels={"revenue": "Revenue (₹)", "month": "Month"},
            )
            fig.update_traces(line_color=ACCENT, hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if daily.empty:
            empty("No daily sales for the current filters.")
        else:
            fig = px.area(
                daily,
                x="date",
                y="revenue",
                labels={"revenue": "Revenue (₹)", "date": "Date"},
            )
            fig.update_traces(line_color=ACCENT, hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)


def category_section(filters: dict) -> None:
    section("Sales by Category", "Revenue grouped by category and subcategory ($group stage).")
    by_category = to_frame(query("get_sales_by_category", filters))
    by_subcategory = to_frame(query("get_sales_by_subcategory", filters))
    left, right = st.columns(2)

    with left:
        if by_category.empty:
            empty("No category data for the current filters.")
        else:
            fig = px.bar(
                by_category.sort_values("revenue"),
                x="revenue",
                y="category",
                orientation="h",
                color="revenue",
                color_continuous_scale=[ "#dbeafe", ACCENT],
                labels={"revenue": "Revenue (₹)", "category": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if by_subcategory.empty:
            empty("No subcategory data for the current filters.")
        else:
            fig = px.bar(
                by_subcategory.sort_values("revenue"),
                x="revenue",
                y="subcategory",
                orientation="h",
                color="revenue",
                color_continuous_scale=["#fef3c7", "#f59e0b"],
                labels={"revenue": "Revenue (₹)", "subcategory": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)


def geography_section(filters: dict) -> None:
    section("Geographical Analysis", "Top cities and all states ranked by revenue.")
    by_city = to_frame(query("get_sales_by_city", filters))
    by_state = to_frame(query("get_sales_by_state", filters))
    left, right = st.columns(2)

    with left:
        if by_city.empty:
            empty("No city data for the current filters.")
        else:
            fig = px.bar(
                by_city.sort_values("revenue"),
                x="revenue",
                y="city",
                orientation="h",
                color="revenue",
                color_continuous_scale=["#dcfce7", "#10b981"],
                labels={"revenue": "Revenue (₹)", "city": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=380)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if by_state.empty:
            empty("No state data for the current filters.")
        else:
            fig = px.bar(
                by_state.sort_values("revenue"),
                x="revenue",
                y="state",
                orientation="h",
                color="revenue",
                color_continuous_scale=["#ede9fe", "#8b5cf6"],
                labels={"revenue": "Revenue (₹)", "state": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=380)
            st.plotly_chart(fig, use_container_width=True)


def product_section(filters: dict) -> None:
    section("Product Analysis", "Best and worst products ranked by revenue.")
    top = to_frame(query("get_top_products", filters))
    bottom = to_frame(query("get_bottom_products", filters))
    left, right = st.columns(2)

    with left:
        if top.empty:
            empty("No product data for the current filters.")
        else:
            top = top.sort_values("revenue")
            fig = px.bar(
                top,
                x="revenue",
                y="product_name",
                orientation="h",
                color="revenue",
                color_continuous_scale=["#dbeafe", ACCENT],
                hover_data=["product_id", "category", "quantity", "orders"],
                labels={"revenue": "Revenue (₹)", "product_name": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=380)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if bottom.empty:
            empty("No product data for the current filters.")
        else:
            bottom = bottom.sort_values("revenue")
            fig = px.bar(
                bottom,
                x="revenue",
                y="product_name",
                orientation="h",
                color="revenue",
                color_continuous_scale=["#fee2e2", "#ef4444"],
                hover_data=["product_id", "category", "quantity", "orders"],
                labels={"revenue": "Revenue (₹)", "product_name": ""},
            )
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=380)
            st.plotly_chart(fig, use_container_width=True)


def customer_section(filters: dict) -> None:
    section("Top Customers", "Customers ranked by total spending ($group on customer_id).")
    customers = to_frame(query("get_top_customers", filters))
    if customers.empty:
        empty("No customer data for the current filters.")
        return

    display = customers.copy()
    display["revenue"] = display["revenue"].map(money)
    display.index = range(1, len(display) + 1)
    display.index.name = "#"
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(display, use_container_width=True)
    with right:
        chart_data = customers.sort_values("revenue")
        fig = px.bar(
            chart_data,
            x="revenue",
            y="customer_name",
            orientation="h",
            color="revenue",
            color_continuous_scale=["#dbeafe", ACCENT],
            labels={"revenue": "Revenue (₹)", "customer_name": ""},
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0), height=340)
        st.plotly_chart(fig, use_container_width=True)


def payment_status_section(filters: dict) -> None:
    section("Payment & Order Status", "Share of orders per payment method and order status.")
    payments = to_frame(query("get_payment_method_distribution", filters))
    statuses = to_frame(query("get_order_status_distribution", filters))
    left, right = st.columns(2)

    with left:
        if payments.empty:
            empty("No payment data for the current filters.")
        else:
            fig = px.pie(
                payments,
                names="payment_method",
                values="orders",
                hole=0.55,
                color_discrete_sequence=PALETTE,
                labels={"orders": "Orders"},
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340,
                              legend=dict(orientation="h", y=-0.1))
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if statuses.empty:
            empty("No order status data for the current filters.")
        else:
            fig = px.pie(
                statuses,
                names="order_status",
                values="orders",
                hole=0.55,
                color_discrete_sequence=PALETTE[::-1],
                labels={"orders": "Orders"},
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340,
                              legend=dict(orientation="h", y=-0.1))
            st.plotly_chart(fig, use_container_width=True)


def demographic_section(filters: dict) -> None:
    section("Customer Demographics", "Revenue by gender and by age group.")
    gender = to_frame(query("get_sales_by_gender", filters))
    ages = to_frame(query("get_sales_by_age_group", filters))
    left, right = st.columns(2)

    with left:
        if gender.empty:
            empty("No gender data for the current filters.")
        else:
            fig = px.pie(
                gender,
                names="gender",
                values="orders",
                hole=0.55,
                color_discrete_sequence=PALETTE,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340,
                              legend=dict(orientation="h", y=-0.1))
            st.plotly_chart(fig, use_container_width=True)

    with right:
        if ages.empty:
            empty("No age data for the current filters.")
        else:
            fig = px.bar(
                ages,
                x="age_group",
                y="revenue",
                color="age_group",
                color_discrete_sequence=PALETTE,
                labels={"revenue": "Revenue (₹)", "age_group": "Age group"},
            )
            fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), height=340)
            st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    st.title("MongoDB Big Data Analytics Dashboard")
    st.caption(
        "Large dataset → ingestion → MongoDB storage → indexing → "
        "aggregation pipelines → analytics → visualization"
    )

    if not database.is_mongodb_available():
        st.error(
            "MongoDB is not reachable at "
            f"{config.redact_uri(config.get_mongo_uri())}. Start the MongoDB "
            "service and press Refresh."
        )
        st.stop()

    server_version = None
    try:
        server_version = database.get_client().server_info().get("version")
    except Exception:  # noqa: BLE001 - version is informational only
        pass

    if "filter_options" not in st.session_state:
        with st.spinner("Loading filter options from MongoDB ..."):
            try:
                st.session_state["filter_options"] = load_filter_options()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read the collection: {exc}")
                st.stop()

    filters = build_sidebar()
    sidebar_status(True, server_version)

    options = st.session_state["filter_options"]
    if options["document_count"] == 0:
        st.warning(
            "The sales collection is empty. Import the dataset first:\n\n"
            "`python src/import_data.py --file data/sales_data_100000.csv`"
        )
        st.stop()

    active = [f"{key}: {value}" for key, value in filters.items()]
    if active:
        st.caption("Active filters → " + " | ".join(active))

    try:
        with st.spinner("Running MongoDB aggregation pipelines ..."):
            kpis = query("get_kpis", filters)
        kpi_row(kpis)

        if kpis["total_orders"] == 0:
            st.info("No documents match the current filters. Clear or change the filters.")
            return

        time_section(filters)
        st.markdown("---")
        category_section(filters)
        st.markdown("---")
        geography_section(filters)
        st.markdown("---")
        product_section(filters)
        st.markdown("---")
        customer_section(filters)
        st.markdown("---")
        payment_status_section(filters)
        st.markdown("---")
        demographic_section(filters)
    except Exception as exc:  # noqa: BLE001 - never show a blank crash page
        st.exception(exc)
        st.error("Something went wrong while running the analytics queries.")


if __name__ == "__main__":
    main()
