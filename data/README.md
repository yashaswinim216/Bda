# Dataset

The official dataset of this project is:

```
data/sales_data_100000.csv
```

- **100,000 records**, **20 columns**
- Synthetic e-commerce sales data for India (NOT real customer data)
- Columns: `order_id, customer_id, customer_name, age, gender, city, state,
  product_id, product_name, category, subcategory, quantity, unit_price,
  discount, payment_method, order_date, delivery_days, order_status, rating,
  total_amount`

## Why is the CSV not in Git?

The file is about 14 MB. Committing large data files makes the repository
slow and bloated, so `data/*.csv` is listed in `.gitignore`. Only this
README and `.gitkeep` are tracked.

## How to obtain the dataset

1. **Use the supplied file** - copy `sales_data_100000.csv` from your
   download location into this `data/` folder:

   ```bat
   copy %USERPROFILE%\Downloads\sales_data_100000.csv data\
   ```

2. **Or generate a dataset** with the included generator:

   ```bat
   python src/generate_data.py --records 100000
   ```

   Larger datasets (500,000 / 1,000,000 records) can also be generated for
   scalability testing:

   ```bat
   python src/generate_data.py --records 500000 --output data/sales_data_500000.csv
   ```

Never overwrite `sales_data_100000.csv`; it is the official project dataset.
