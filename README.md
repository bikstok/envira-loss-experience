# Envira Loss-Experience Service

A lightweight, production-ready analytics service backed by SQLite and FastAPI reporting loss experience across Danish property insurance portfolios for underwriting and climate risk pricing. Data is ingested into relational SQLite tables on startup with indexed SQL queries for sub-millisecond filtering and aggregation.

---

## 1. Quickstart

### Prerequisites
- Docker & Docker Compose

### Data Placement
Ensure the raw CSV data files are located in the `./data/` directory at the project root:
```text
./data/
├── assets.csv
├── policies.csv
├── claims.csv
└── fx_rates.csv
```
*(Note: Per the assessment brief, `./data/` is excluded from git version control via `.gitignore`.)*

### Run with Docker Compose
Start the service in the background on port `8000`:
```bash
docker compose up --build -d
```

Check status and health:
```bash
docker compose ps
```

The interactive dashboard is available at: **`http://localhost:8000/`**  
Interactive API docs (Swagger): **`http://localhost:8000/docs`**

To stop the service:
```bash
docker compose down
```

---

## 2. Running Automated Tests

Run the test suite inside the container environment with data mounted read-only:
```bash
docker run --rm -v $(pwd)/data:/app/data:ro envira_test-loss-experience-api pytest -v
```

---

## 3. API Endpoints

### Core Loss Experience: `GET /portfolios/{portfolio_id}/loss-experience`
Returns peril-level loss experience (`policy_count`, `earned_premium`, `incurred_loss`, `loss_ratio`, `claim_count`, `largest_single_claim` in DKK) and portfolio totals.
```bash
curl -s http://localhost:8000/portfolios/PF-01/loss-experience
```
**Optional Filters:**
- `underwriting_year`: Policy inception year (e.g., `?underwriting_year=2023`)
- `region`: Asset region (e.g., `?region=Syddanmark`)
- `asset_type`: Asset type (e.g., `?asset_type=residential`)

### Portfolio Comparison & Ranking: `GET /portfolios/loss-experience`
Compares all portfolios ranked by underwriting performance metrics.
```bash
curl -s "http://localhost:8000/portfolios/loss-experience?sort_by=loss_ratio&order=desc"
```
**Query Parameters:**
- `sort_by`: `loss_ratio` (default), `incurred_loss`, `earned_premium`, `policy_count`, `claim_count`, `portfolio_id`
- `order`: `desc` (default) or `asc`

### Data Quality & Exclusions Report: `GET /data-quality`
Provides transparency on data hygiene, normalization, and handling of dirty records.
```bash
curl -s http://localhost:8000/data-quality
```

### Health Check: `GET /health`
```bash
curl -s http://localhost:8000/health
```

---

## 4. Business & Accounting Policies

- **Earned Premium:** 100% of policy annual premium earned; converted to DKK using the exchange rate at policy inception month.
- **Incurred Loss:** Settled claims = `paid_amount`; Open claims = `paid_amount + reserve_amount`; Withdrawn/Declined = `0.0`. Converted to DKK using the rate at `loss_date` month.
- **Negative Paid Amounts:** 262 settled claims have negative paid amounts. In insurance accounting, these reflect recoveries or salvage subrogations, reducing total incurred losses.
- **Orphaned Claims:** 260 claims reference non-existent `policy_id`s and cannot be linked to any asset/portfolio. They are excluded from portfolio calculations and reported in `/data-quality`.
- **Pre-Inception Loss Dates:** 310 claims with `loss_date < inception_date` are retained under their assigned policy per brief guidance ("*A claim belongs to a policy*").
