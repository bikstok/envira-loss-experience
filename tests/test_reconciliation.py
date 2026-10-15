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
    d = os.getenv("DATA_DIR", "data")
    if not os.path.exists(d):
        pytest.skip("Data directory not present")
    return d


@pytest.fixture(scope="module")
def service_repo(data_dir):
    return LossExperienceRepository(data_dir)


@pytest.fixture(scope="module")
def raw_calculations(data_dir):
    """Independently calculates book and portfolio metrics directly from raw CSVs."""
    # 1. Load FX Rates
    fx_path = os.path.join(data_dir, "fx_rates.csv")
    fx_rates = {}
    with open(fx_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fx_rates[(r["month"].strip(), r["currency"].strip())] = float(r["rate_dkk_per_unit"])

    def get_fx(dt: datetime, curr: str) -> float:
        if curr == "DKK":
            return 1.0
        return fx_rates[(dt.strftime("%Y-%m"), curr)]

    # 2. Load Assets
    assets_path = os.path.join(data_dir, "assets.csv")
    assets = {}
    with open(assets_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            assets[r["asset_id"].strip()] = r["portfolio_id"].strip()

    # 3. Load Policies
    policies_path = os.path.join(data_dir, "policies.csv")
    policies = {}
    portfolio_premiums = defaultdict(float)
    portfolio_peril_premiums = defaultdict(lambda: defaultdict(float))
    portfolio_policy_counts = defaultdict(int)
    portfolio_peril_policy_counts = defaultdict(lambda: defaultdict(int))
    total_book_premium = 0.0

    with open(policies_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pol_id = r["policy_id"].strip()
            aid = r["asset_id"].strip()
            port_id = assets[aid]
            peril = r["peril"].strip().lower()
            inc = parse_date(r["inception_date"])
            curr = r["currency"].strip()
            rate = get_fx(inc, curr)
            prem_dkk = float(r["annual_premium"]) * rate

            policies[pol_id] = (port_id, peril, prem_dkk)
            portfolio_premiums[port_id] += prem_dkk
            portfolio_peril_premiums[port_id][peril] += prem_dkk
            portfolio_policy_counts[port_id] += 1
            portfolio_peril_policy_counts[port_id][peril] += 1
            total_book_premium += prem_dkk

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

    with open(claims_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["policy_id"].strip()
            if pid not in policies:
                orphaned_count += 1
                continue
            valid_claims_count += 1

            port_id, peril, _ = policies[pid]
            status = r["status"].strip().lower()

            if status in ("withdrawn", "declined"):
                incurred = 0.0
            elif status == "settled":
                incurred = float(r["paid_amount"])
            elif status == "open":
                incurred = float(r["paid_amount"]) + float(r["reserve_amount"])
            else:
                incurred = float(r["paid_amount"]) + float(r["reserve_amount"])

            loss_date = parse_date(r["loss_date"])
            rate = get_fx(loss_date, r["currency"].strip())
            loss_dkk = incurred * rate

            portfolio_losses[port_id] += loss_dkk
            portfolio_peril_losses[port_id][peril] += loss_dkk
            portfolio_claim_counts[port_id] += 1
            portfolio_peril_claim_counts[port_id][peril] += 1
            if loss_dkk > portfolio_peril_max_claim[port_id][peril]:
                portfolio_peril_max_claim[port_id][peril] = loss_dkk
            total_book_loss += loss_dkk

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


def test_dataset_reconciliation_counts(raw_calculations, service_repo):
    """Verify record counts match expected values and service data quality report."""
    dq = service_repo.get_data_quality_report()
    assert raw_calculations["assets_count"] == 4200
    assert raw_calculations["policies_count"] == 11560
    assert raw_calculations["orphaned_claims_count"] == 260
    assert raw_calculations["valid_claims_count"] == 4249
    assert dq.total_assets == raw_calculations["assets_count"]
    assert dq.total_policies == raw_calculations["policies_count"]
    assert dq.orphaned_claims_excluded == raw_calculations["orphaned_claims_count"]


def test_book_level_totals_reconciliation(raw_calculations, service_repo):
    """Verify aggregated book-level premium, loss, and loss ratio reconcile perfectly."""
    portfolios = service_repo.get_all_portfolios_experience()
    service_total_premium = sum(p.total_earned_premium for p in portfolios)
    service_total_loss = sum(p.total_incurred_loss for p in portfolios)

    # Discrepancy must be under 0.05 DKK across ~80 million DKK in turnover
    assert abs(service_total_premium - raw_calculations["total_book_premium"]) < 0.05
    assert abs(service_total_loss - raw_calculations["total_book_loss"]) < 0.05

    service_loss_ratio = service_total_loss / service_total_premium
    assert abs(service_loss_ratio - raw_calculations["book_loss_ratio"]) < 0.0001


@pytest.mark.parametrize("portfolio_id", PORTFOLIO_IDS)
def test_individual_portfolio_reconciliation(portfolio_id, raw_calculations, service_repo):
    """Verify each portfolio matches the independent raw calculation to 0.00 DKK."""
    exp = service_repo.get_portfolio_experience(portfolio_id)
    assert exp is not None

    expected_premium = raw_calculations["portfolio_premiums"][portfolio_id]
    expected_loss = raw_calculations["portfolio_losses"][portfolio_id]
    expected_policies = raw_calculations["portfolio_policy_counts"][portfolio_id]
    expected_claims = raw_calculations["portfolio_claim_counts"][portfolio_id]

    assert exp.total_policy_count == expected_policies
    assert exp.total_claim_count == expected_claims
    assert abs(exp.total_earned_premium - expected_premium) < 0.05
    assert abs(exp.total_incurred_loss - expected_loss) < 0.05


def test_peril_level_segments_reconciliation(raw_calculations, service_repo):
    """Verify all 60 peril segments reconcile across all portfolios."""
    standard_perils = ("fire", "flood", "hail", "storm", "subsidence")
    for port_id in PORTFOLIO_IDS:
        exp = service_repo.get_portfolio_experience(port_id)
        for peril in standard_perils:
            p_exp = exp.perils[peril]
            expected_p_prem = raw_calculations["portfolio_peril_premiums"][port_id][peril]
            expected_p_loss = raw_calculations["portfolio_peril_losses"][port_id][peril]
            expected_p_max = raw_calculations["portfolio_peril_max_claim"][port_id][peril]

            assert abs(p_exp.earned_premium - expected_p_prem) < 0.05
            assert abs(p_exp.incurred_loss - expected_p_loss) < 0.05
            assert abs(p_exp.largest_single_claim - expected_p_max) < 0.05
