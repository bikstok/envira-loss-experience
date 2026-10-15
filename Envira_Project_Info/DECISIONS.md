Started: 2026-10-15 14:10 CEST
Stopped: 2026-10-15 16:10 CEST

- **What I built**
  - Core loss experience engine: `GET /portfolios/{portfolio_id}/loss-experience` returning peril breakdowns (policy count, earned premium, incurred loss, loss ratio, claim count, largest claim) in DKK.
  - SQLite relational backend (Item 8): normalized tables (`assets`, `policies`, `claims`, `fx_rates`), relational indexes, and parameterized SQL queries for aggregation and filtering.
  - Portfolio comparison endpoint (`GET /portfolios/loss-experience`) with configurable rankings, plus filtering by underwriting year, region, and asset type.
  - Strict query input validation: returning clear HTTP 400 Bad Request responses with allowable options for invalid sort metrics, orders, regions, asset types, or underwriting years.
  - WebInterfacer on http://localhost:8000/ where end an user can interactivly view the results.
  - Data quality audit endpoint (`GET /data-quality`) and an interactive web dashboard (`GET /`) for non-technical underwriters.
  - Ingestion pipeline normalizing 1,321 dirty peril strings (`.strip().lower()`), parsing European and ISO date formats, and applying monthly FX rates.
  - Independent reconciliation test suite (`tests/test_reconciliation.py`): decoupled mathematical verification independently computing raw totals and asserting 0.00 DKK discrepancy across the whole book, each individual portfolio (`PF-01`–`PF-12`), and all 60 peril segments.
  - Layered separation of concerns: structured codebase across domain models (`src/models.py`), data access repository (`src/repository.py`), input validators (`src/validators.py`), and a slim FastAPI controller (`src/main.py`).
  - Full Docker and Compose configuration with automated healthcheck and pytest suite.
  - Developer tooling: `Makefile` supporting `start`, `stop`, `restart`, `test`, `status`, `logs`, and `clean`.

- **What I deliberately did not build, and why**
  - External database service (Postgres container / Kafka / Celery): Python's standard library `sqlite3` satisfies the database requirement with zero network latency, zero container sprawl, and instant boot times.
  - React/npm build pipeline: Kept the UI zero-dependency (native HTML5/vanilla JS served directly from FastAPI) for immediate runnability without node_modules bloat.
  - Excluded 260 orphaned claims lacking valid policy IDs, cataloging them transparently in the quality report rather than guessing associations.

- **What I would do first with another day**
  - Implement automated re-attribution for the 83 claims that occurred before policy inception but match an earlier active policy term for the same asset and peril.
  - Add Parquet/CSV export endpoints and historical development triangulations for actuary reporting.
  - Add CI/CD, linting, and formater.

*(AI tool note: Used Gemini/Claude CLI agent. Verified and rejected naive string slicing for FX lookups after discovering European date formats (`DD-MM-YYYY`), replacing it with explicit multi-format date parsing which resolved 572 date/FX mismatch errors.)*
