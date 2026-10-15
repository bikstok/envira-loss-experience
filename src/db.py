"""SQLite schema definition, indexing, and ingestion pipeline."""

import csv
import os
import sqlite3
from datetime import datetime
from typing import Dict, Tuple


def parse_date_to_iso(date_str: str) -> str:
    """Parse mixed date formats (ISO or European) to canonical ISO 'YYYY-MM-DD'."""
    cleaned_date_str = date_str.strip()
    for date_format in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned_date_str, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


def init_db(connection: sqlite3.Connection):
    """Create normalized relational tables and performance indexes."""
    cursor = connection.cursor()
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
    connection.commit()


def load_csv_data_to_sqlite(connection: sqlite3.Connection, data_dir: str):
    """Load and normalize raw CSV datasets into SQLite tables."""
    cursor = connection.cursor()

    # 1. Load FX Rates
    fx_rates_path = os.path.join(data_dir, "fx_rates.csv")
    fx_rates: Dict[Tuple[str, str], float] = {}
    with open(fx_rates_path, newline="", encoding="utf-8") as fx_file:
        fx_reader = csv.DictReader(fx_file)
        fx_table_rows = []
        for row in fx_reader:
            month = row["month"].strip()
            currency = row["currency"].strip()
            exchange_rate = float(row["rate_dkk_per_unit"])
            fx_rates[(month, currency)] = exchange_rate
            fx_table_rows.append((month, currency, exchange_rate))
        cursor.executemany(
            "INSERT OR REPLACE INTO fx_rates VALUES (?, ?, ?)", fx_table_rows
        )

    # Helper for FX conversion
    def get_exchange_rate(iso_date: str, currency: str) -> float:
        if currency == "DKK":
            return 1.0
        month_key = iso_date[:7]
        rate = fx_rates.get((month_key, currency))
        if rate is None:
            raise KeyError(f"Missing FX rate for month {month_key} and currency {currency}")
        return rate

    # 2. Load Assets
    assets_path = os.path.join(data_dir, "assets.csv")
    with open(assets_path, newline="", encoding="utf-8") as assets_file:
        assets_reader = csv.DictReader(assets_file)
        asset_table_rows = [
            (
                row["asset_id"].strip(),
                row["portfolio_id"].strip(),
                row["region"].strip(),
                row["asset_type"].strip(),
                int(row["construction_year"]),
                float(row["sum_insured_dkk"]),
            )
            for row in assets_reader
        ]
        cursor.executemany("INSERT OR REPLACE INTO assets VALUES (?, ?, ?, ?, ?, ?)", asset_table_rows)

    # 3. Load Policies
    policies_path = os.path.join(data_dir, "policies.csv")
    known_policy_ids = set()
    policy_inceptions: Dict[str, str] = {}
    non_standard_perils_count = 0
    european_dates_count = 0

    with open(policies_path, newline="", encoding="utf-8") as policies_file:
        policies_reader = csv.DictReader(policies_file)
        policy_table_rows = []
        for row in policies_reader:
            raw_peril = row["peril"]
            normalized_peril = raw_peril.strip().lower()
            if raw_peril != normalized_peril:
                non_standard_perils_count += 1

            raw_inception_date = row["inception_date"].strip()
            if "-" in raw_inception_date and raw_inception_date[2] == "-":
                european_dates_count += 1
            iso_inception_date = parse_date_to_iso(raw_inception_date)

            raw_expiry_date = row["expiry_date"].strip()
            if "-" in raw_expiry_date and raw_expiry_date[2] == "-":
                european_dates_count += 1
            iso_expiry_date = parse_date_to_iso(raw_expiry_date)

            policy_id = row["policy_id"].strip()
            known_policy_ids.add(policy_id)
            policy_inceptions[policy_id] = iso_inception_date

            currency = row["currency"].strip()
            annual_premium = float(row["annual_premium"])
            exchange_rate = get_exchange_rate(iso_inception_date, currency)
            earned_premium_dkk = annual_premium * exchange_rate
            underwriting_year = int(iso_inception_date[:4])

            policy_table_rows.append(
                (
                    policy_id,
                    row["asset_id"].strip(),
                    normalized_peril,
                    iso_inception_date,
                    iso_expiry_date,
                    annual_premium,
                    currency,
                    underwriting_year,
                    earned_premium_dkk,
                )
            )
        cursor.executemany(
            "INSERT OR REPLACE INTO policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", policy_table_rows
        )

    # 4. Load Claims
    claims_path = os.path.join(data_dir, "claims.csv")
    orphaned_claims_count = 0
    claims_before_inception_count = 0
    negative_paid_claims_count = 0

    with open(claims_path, newline="", encoding="utf-8") as claims_file:
        claims_reader = csv.DictReader(claims_file)
        claim_table_rows = []
        for row in claims_reader:
            policy_id = row["policy_id"].strip()
            if policy_id not in known_policy_ids:
                orphaned_claims_count += 1
                continue

            raw_loss_date = row["loss_date"].strip()
            if "-" in raw_loss_date and raw_loss_date[2] == "-":
                european_dates_count += 1
            iso_loss_date = parse_date_to_iso(raw_loss_date)

            raw_reported_date = row["reported_date"].strip()
            if "-" in raw_reported_date and raw_reported_date[2] == "-":
                european_dates_count += 1
            iso_reported_date = parse_date_to_iso(raw_reported_date)

            if iso_loss_date < policy_inceptions[policy_id]:
                claims_before_inception_count += 1

            paid_amount = float(row["paid_amount"])
            reserve_amount = float(row["reserve_amount"])
            if paid_amount < 0 or reserve_amount < 0:
                negative_paid_claims_count += 1

            currency = row["currency"].strip()
            claim_status = row["status"].strip().lower()

            if claim_status in ("withdrawn", "declined"):
                incurred_loss_original_currency = 0.0
            elif claim_status == "settled":
                incurred_loss_original_currency = paid_amount
            elif claim_status == "open":
                incurred_loss_original_currency = paid_amount + reserve_amount
            else:
                incurred_loss_original_currency = paid_amount + reserve_amount

            exchange_rate = get_exchange_rate(iso_loss_date, currency)
            incurred_loss_dkk = incurred_loss_original_currency * exchange_rate

            claim_table_rows.append(
                (
                    row["claim_id"].strip(),
                    policy_id,
                    iso_loss_date,
                    iso_reported_date,
                    paid_amount,
                    reserve_amount,
                    currency,
                    claim_status,
                    incurred_loss_dkk,
                )
            )
        cursor.executemany(
            "INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", claim_table_rows
        )

    # 5. Record data quality metrics
    metrics_records = [
        ("orphaned_claims_excluded", orphaned_claims_count),
        ("claims_loss_before_inception_retained", claims_before_inception_count),
        ("negative_paid_claims_retained", negative_paid_claims_count),
        ("non_standard_perils_normalized", non_standard_perils_count),
        ("european_dates_parsed", european_dates_count),
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO data_quality_metrics VALUES (?, ?)", metrics_records
    )
    connection.commit()
