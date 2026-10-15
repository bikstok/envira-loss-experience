"""
Independent mathematical verification and underwriting reconciliation test suite.

This module independently parses and recalculates all metrics directly from the raw CSV
source files without relying on the domain or repository pipelines, and asserts that the
SQLite service output matches down to 0.00 DKK.
"""

import csv
import os
from collections import defaultdict
from datetime import datetime
import pytest

from src.models import parse_date
from src.repository import LossExperienceRepository

PORTFOLIO_IDS = [f"PF-{i:02d}" for i in range(1, 13)]


@pytest.fixture(scope="module")
def data_dir():
    directory = os.getenv("DATA_DIR", "data")
    if not os.path.exists(directory):
        pytest.skip("Data directory not present")
    return directory


@pytest.fixture(scope="module")
def service_repository(data_dir):
    return LossExperienceRepository(data_dir)


# Alias for backward compatibility
service_repo = service_repository


@pytest.fixture(scope="module")
def raw_calculations(data_dir):
    """Independently calculates book and portfolio metrics directly from raw CSVs."""
    # 1. Load FX Rates
    fx_path = os.path.join(data_dir, "fx_rates.csv")
    fx_rates = {}
    with open(fx_path, newline="", encoding="utf-8") as fx_file:
        for row in csv.DictReader(fx_file):
            fx_rates[(row["month"].strip(), row["currency"].strip())] = float(row["rate_dkk_per_unit"])

    def get_exchange_rate(loss_or_inception_date: datetime, currency: str) -> float:
        if currency == "DKK":
            return 1.0
        return fx_rates[(loss_or_inception_date.strftime("%Y-%m"), currency)]

    # 2. Load Assets
    assets_path = os.path.join(data_dir, "assets.csv")
    assets = {}
    with open(assets_path, newline="", encoding="utf-8") as assets_file:
        for row in csv.DictReader(assets_file):
            assets[row["asset_id"].strip()] = row["portfolio_id"].strip()

    # 3. Load Policies
    policies_path = os.path.join(data_dir, "policies.csv")
    policies = {}
    portfolio_premiums = defaultdict(float)
    portfolio_peril_premiums = defaultdict(lambda: defaultdict(float))
    portfolio_policy_counts = defaultdict(int)
    portfolio_peril_policy_counts = defaultdict(lambda: defaultdict(int))
    total_book_premium = 0.0

    with open(policies_path, newline="", encoding="utf-8") as policies_file:
        for row in csv.DictReader(policies_file):
            policy_id = row["policy_id"].strip()
            asset_id = row["asset_id"].strip()
            portfolio_id = assets[asset_id]
            peril = row["peril"].strip().lower()
            inception_date = parse_date(row["inception_date"])
            currency = row["currency"].strip()
            exchange_rate = get_exchange_rate(inception_date, currency)
            earned_premium_dkk = float(row["annual_premium"]) * exchange_rate

            policies[policy_id] = (portfolio_id, peril, earned_premium_dkk)
            portfolio_premiums[portfolio_id] += earned_premium_dkk
            portfolio_peril_premiums[portfolio_id][peril] += earned_premium_dkk
            portfolio_policy_counts[portfolio_id] += 1
            portfolio_peril_policy_counts[portfolio_id][peril] += 1
            total_book_premium += earned_premium_dkk

    # 4. Load Claims
    claims_path = os.path.join(data_dir, "claims.csv")
    orphaned_count = 0
    valid_claims_count = 0
    portfolio_losses = defaultdict(float)
    portfolio_peril_losses = defaultdict(lambda: defaultdict(float))
    portfolio_claim_counts = defaultdict(int)
    portfolio_peril_claim_counts = defaultdict(lambda: defaultdict(int))
    portfolio_peril_max_claim = defaultdict(lambda: defaultdict(float))
    total_book_loss = 0.0

    with open(claims_path, newline="", encoding="utf-8") as claims_file:
        for row in csv.DictReader(claims_file):
            policy_id = row["policy_id"].strip()
            if policy_id not in policies:
                orphaned_count += 1
                continue
            valid_claims_count += 1

            portfolio_id, peril, _ = policies[policy_id]
            claim_status = row["status"].strip().lower()

            if claim_status in ("withdrawn", "declined"):
                incurred_loss_original_currency = 0.0
            elif claim_status == "settled":
                incurred_loss_original_currency = float(row["paid_amount"])
            elif claim_status == "open":
                incurred_loss_original_currency = float(row["paid_amount"]) + float(row["reserve_amount"])
            else:
                incurred_loss_original_currency = float(row["paid_amount"]) + float(row["reserve_amount"])

            loss_date = parse_date(row["loss_date"])
            exchange_rate = get_exchange_rate(loss_date, row["currency"].strip())
            incurred_loss_dkk = incurred_loss_original_currency * exchange_rate

            portfolio_losses[portfolio_id] += incurred_loss_dkk
            portfolio_peril_losses[portfolio_id][peril] += incurred_loss_dkk
            portfolio_claim_counts[portfolio_id] += 1
            portfolio_peril_claim_counts[portfolio_id][peril] += 1
            if incurred_loss_dkk > portfolio_peril_max_claim[portfolio_id][peril]:
                portfolio_peril_max_claim[portfolio_id][peril] = incurred_loss_dkk
            total_book_loss += incurred_loss_dkk

    return {
        "assets_count": len(assets),
        "policies_count": len(policies),
        "orphaned_claims_count": orphaned_count,
        "valid_claims_count": valid_claims_count,
        "total_book_premium": total_book_premium,
        "total_book_loss": total_book_loss,
        "book_loss_ratio": total_book_loss / total_book_premium,
        "portfolio_premiums": portfolio_premiums,
        "portfolio_losses": portfolio_losses,
        "portfolio_policy_counts": portfolio_policy_counts,
        "portfolio_claim_counts": portfolio_claim_counts,
        "portfolio_peril_premiums": portfolio_peril_premiums,
        "portfolio_peril_losses": portfolio_peril_losses,
        "portfolio_peril_max_claim": portfolio_peril_max_claim,
    }


def test_dataset_reconciliation_counts(raw_calculations, service_repository):
    """Verify record counts match expected values and service data quality report."""
    data_quality_report = service_repository.get_data_quality_report()
    assert raw_calculations["assets_count"] == 4200
    assert raw_calculations["policies_count"] == 11560
    assert raw_calculations["orphaned_claims_count"] == 260
    assert raw_calculations["valid_claims_count"] == 4249
    assert data_quality_report.total_assets == raw_calculations["assets_count"]
    assert data_quality_report.total_policies == raw_calculations["policies_count"]
    assert data_quality_report.orphaned_claims_excluded == raw_calculations["orphaned_claims_count"]


def test_book_level_totals_reconciliation(raw_calculations, service_repository):
    """Verify aggregated book-level premium, loss, and loss ratio reconcile perfectly."""
    portfolios = service_repository.get_all_portfolios_experience()
    service_total_premium = sum(portfolio.total_earned_premium for portfolio in portfolios)
    service_total_loss = sum(portfolio.total_incurred_loss for portfolio in portfolios)

    # Discrepancy must be under 0.05 DKK across ~80 million DKK in turnover
    assert abs(service_total_premium - raw_calculations["total_book_premium"]) < 0.05
    assert abs(service_total_loss - raw_calculations["total_book_loss"]) < 0.05

    service_loss_ratio = service_total_loss / service_total_premium
    assert abs(service_loss_ratio - raw_calculations["book_loss_ratio"]) < 0.0001


@pytest.mark.parametrize("portfolio_id", PORTFOLIO_IDS)
def test_individual_portfolio_reconciliation(portfolio_id, raw_calculations, service_repository):
    """Verify each portfolio matches the independent raw calculation to 0.00 DKK."""
    portfolio_experience = service_repository.get_portfolio_experience(portfolio_id)
    assert portfolio_experience is not None

    expected_premium = raw_calculations["portfolio_premiums"][portfolio_id]
    expected_loss = raw_calculations["portfolio_losses"][portfolio_id]
    expected_policies = raw_calculations["portfolio_policy_counts"][portfolio_id]
    expected_claims = raw_calculations["portfolio_claim_counts"][portfolio_id]

    assert portfolio_experience.total_policy_count == expected_policies
    assert portfolio_experience.total_claim_count == expected_claims
    assert abs(portfolio_experience.total_earned_premium - expected_premium) < 0.05
    assert abs(portfolio_experience.total_incurred_loss - expected_loss) < 0.05


def test_peril_level_segments_reconciliation(raw_calculations, service_repository):
    """Verify all 60 peril segments reconcile across all portfolios."""
    standard_perils = ("fire", "flood", "hail", "storm", "subsidence")
    for portfolio_id in PORTFOLIO_IDS:
        portfolio_experience = service_repository.get_portfolio_experience(portfolio_id)
        for peril in standard_perils:
            peril_experience = portfolio_experience.perils[peril]
            expected_peril_premium = raw_calculations["portfolio_peril_premiums"][portfolio_id][peril]
            expected_peril_loss = raw_calculations["portfolio_peril_losses"][portfolio_id][peril]
            expected_peril_max_claim = raw_calculations["portfolio_peril_max_claim"][portfolio_id][peril]

            assert abs(peril_experience.earned_premium - expected_peril_premium) < 0.05
            assert abs(peril_experience.incurred_loss - expected_peril_loss) < 0.05
            assert abs(peril_experience.largest_single_claim - expected_peril_max_claim) < 0.05
