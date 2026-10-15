"""SQLite schema definition, indexing, and ingestion pipeline."""

import csv
import os
import sqlite3
from datetime import datetime
from typing import Dict, Tuple


def parse_date_to_iso(date_str: str) -> str:
    """Parse mixed date formats (ISO or European) to canonical ISO 'YYYY-MM-DD'."""
    clean = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


def init_db(conn: sqlite3.Connection):
    """Create normalized relational tables and performance indexes."""
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS fx_rates (
            month TEXT NOT NULL,
            currency TEXT NOT NULL,
            rate_dkk_per_unit REAL NOT NULL,
            PRIMARY KEY (month, currency)
        );

        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            portfolio_id TEXT NOT NULL,
            region TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            construction_year INTEGER NOT NULL,
            sum_insured_dkk REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_assets_portfolio ON assets(portfolio_id);
        CREATE INDEX IF NOT EXISTS idx_assets_region ON assets(region);
        CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(asset_type);

        CREATE TABLE IF NOT EXISTS policies (
            policy_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL REFERENCES assets(asset_id),
            peril TEXT NOT NULL,
            inception_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            annual_premium REAL NOT NULL,
            currency TEXT NOT NULL,
            underwriting_year INTEGER NOT NULL,
            earned_premium_dkk REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_policies_asset ON policies(asset_id);
        CREATE INDEX IF NOT EXISTS idx_policies_peril ON policies(peril);
        CREATE INDEX IF NOT EXISTS idx_policies_year ON policies(underwriting_year);

        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL REFERENCES policies(policy_id),
            loss_date TEXT NOT NULL,
            reported_date TEXT NOT NULL,
            paid_amount REAL NOT NULL,
            reserve_amount REAL NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            incurred_loss_dkk REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_claims_policy ON claims(policy_id);
        CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);

        CREATE TABLE IF NOT EXISTS data_quality_metrics (
            metric_key TEXT PRIMARY KEY,
            metric_value INTEGER NOT NULL
        );
    """)
    conn.commit()


def load_csv_data_to_sqlite(conn: sqlite3.Connection, data_dir: str):
    """Load and normalize raw CSV datasets into SQLite tables."""
    cursor = conn.cursor()

    # 1. Load FX Rates
    fx_path = os.path.join(data_dir, "fx_rates.csv")
    fx_rates: Dict[Tuple[str, str], float] = {}
    with open(fx_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fx_rows = []
        for r in reader:
            month = r["month"].strip()
            curr = r["currency"].strip()
            rate = float(r["rate_dkk_per_unit"])
            fx_rates[(month, curr)] = rate
            fx_rows.append((month, curr, rate))
        cursor.executemany(
            "INSERT OR REPLACE INTO fx_rates VALUES (?, ?, ?)", fx_rows
        )

    # Helper for FX conversion
    def get_fx(iso_date: str, currency: str) -> float:
        if currency == "DKK":
            return 1.0
        month_key = iso_date[:7]
        rate = fx_rates.get((month_key, currency))
        if rate is None:
            raise KeyError(f"Missing FX rate for month {month_key} and currency {currency}")
        return rate

    # 2. Load Assets
    assets_path = os.path.join(data_dir, "assets.csv")
    with open(assets_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        asset_rows = [
            (
                r["asset_id"].strip(),
                r["portfolio_id"].strip(),
                r["region"].strip(),
                r["asset_type"].strip(),
                int(r["construction_year"]),
                float(r["sum_insured_dkk"]),
            )
            for r in reader
        ]
        cursor.executemany("INSERT OR REPLACE INTO assets VALUES (?, ?, ?, ?, ?, ?)", asset_rows)

    # 3. Load Policies
    policies_path = os.path.join(data_dir, "policies.csv")
    policy_ids = set()
    policy_inceptions: Dict[str, str] = {}
    non_standard_perils = 0
    european_dates = 0

    with open(policies_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        policy_rows = []
        for r in reader:
            raw_peril = r["peril"]
            norm_peril = raw_peril.strip().lower()
            if raw_peril != norm_peril:
                non_standard_perils += 1

            inc_raw = r["inception_date"].strip()
            if "-" in inc_raw and inc_raw[2] == "-":
                european_dates += 1
            inc_iso = parse_date_to_iso(inc_raw)

            exp_raw = r["expiry_date"].strip()
            if "-" in exp_raw and exp_raw[2] == "-":
                european_dates += 1
            exp_iso = parse_date_to_iso(exp_raw)

            pol_id = r["policy_id"].strip()
            policy_ids.add(pol_id)
            policy_inceptions[pol_id] = inc_iso

            curr = r["currency"].strip()
            annual_prem = float(r["annual_premium"])
            fx_rate = get_fx(inc_iso, curr)
            earned_prem_dkk = annual_prem * fx_rate
            uw_year = int(inc_iso[:4])

            policy_rows.append(
                (
                    pol_id,
                    r["asset_id"].strip(),
                    norm_peril,
                    inc_iso,
                    exp_iso,
                    annual_prem,
                    curr,
                    uw_year,
                    earned_prem_dkk,
                )
            )
        cursor.executemany(
            "INSERT OR REPLACE INTO policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", policy_rows
        )

    # 4. Load Claims
    claims_path = os.path.join(data_dir, "claims.csv")
    orphaned_claims = 0
    claims_before_inception = 0
    negative_paid_claims = 0

    with open(claims_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        claim_rows = []
        for r in reader:
            pol_id = r["policy_id"].strip()
            if pol_id not in policy_ids:
                orphaned_claims += 1
                continue

            loss_raw = r["loss_date"].strip()
            if "-" in loss_raw and loss_raw[2] == "-":
                european_dates += 1
            loss_iso = parse_date_to_iso(loss_raw)

            rep_raw = r["reported_date"].strip()
            if "-" in rep_raw and rep_raw[2] == "-":
                european_dates += 1
            rep_iso = parse_date_to_iso(rep_raw)

            if loss_iso < policy_inceptions[pol_id]:
                claims_before_inception += 1

            paid = float(r["paid_amount"])
            res = float(r["reserve_amount"])
            if paid < 0 or res < 0:
                negative_paid_claims += 1

            curr = r["currency"].strip()
            status = r["status"].strip().lower()

            if status in ("withdrawn", "declined"):
                incurred_orig = 0.0
            elif status == "settled":
                incurred_orig = paid
            elif status == "open":
                incurred_orig = paid + res
            else:
                incurred_orig = paid + res

            fx_rate = get_fx(loss_iso, curr)
            incurred_dkk = incurred_orig * fx_rate

            claim_rows.append(
                (
                    r["claim_id"].strip(),
                    pol_id,
                    loss_iso,
                    rep_iso,
                    paid,
                    res,
                    curr,
                    status,
                    incurred_dkk,
                )
            )
        cursor.executemany(
            "INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", claim_rows
        )

    # 5. Record data quality metrics
    metrics = [
        ("orphaned_claims_excluded", orphaned_claims),
        ("claims_loss_before_inception_retained", claims_before_inception),
        ("negative_paid_claims_retained", negative_paid_claims),
        ("non_standard_perils_normalized", non_standard_perils),
        ("european_dates_parsed", european_dates),
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO data_quality_metrics VALUES (?, ?)", metrics
    )
    conn.commit()
