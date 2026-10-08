# MongoDB-Based Big Data Storage, Processing and Analytics System

> BTech academic project: store a large e-commerce dataset in MongoDB,
> process it with aggregation pipelines, analyze it with Python and
> visualize it with an interactive Streamlit dashboard.

**STORE → PROCESS → ANALYZE → VISUALIZE**

## Overview

_See the full documentation in the final version of this README._

## Quick start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python src/validate_data.py --file data/sales_data_100000.csv
python src/import_data.py --file data/sales_data_100000.csv
python src/indexes.py
pytest
streamlit run dashboard/app.py
```

## License

MIT - see [LICENSE](LICENSE).
