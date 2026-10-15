"""Unit and integration tests for the Envira Loss Experience Service."""

import os
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from src.domain import (
    parse_date,
    LossExperienceRepository,
    PerilExperience,
    PortfolioExperience,
)
from src.main import app


def test_parse_date_iso_and_european():
    assert parse_date("2023-06-19") == datetime(2023, 6, 19)
    assert parse_date("19-06-2023") == datetime(2023, 6, 19)
    assert parse_date(" 2024-01-01 ") == datetime(2024, 1, 1)

    with pytest.raises(ValueError):
        parse_date("not-a-date")


def test_peril_experience_loss_ratio():
    p = PerilExperience(
        peril="storm",
        policy_count=10,
        earned_premium=100000.0,
        incurred_loss=60000.0,
        claim_count=3,
        largest_single_claim=30000.0,
    )
    p.loss_ratio = p.incurred_loss / p.earned_premium
    d = p.to_dict()
    assert d["loss_ratio"] == 0.6
    assert d["earned_premium"] == 100000.0
    assert d["incurred_loss"] == 60000.0


def test_repository_loading():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repo = LossExperienceRepository(data_dir)
    dq = repo.get_data_quality_report()
    assert dq.total_assets == 4200
    assert dq.total_policies == 11560
    assert dq.orphaned_claims_excluded == 260
    assert dq.claims_loss_before_inception == 310
    assert dq.negative_paid_claims == 262
    assert len(repo.get_portfolio_ids()) == 12
    assert repo.total_policies_count == 11560


def test_sqlite_direct_query():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repo = LossExperienceRepository(data_dir)
    cursor = repo.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM assets")
    assert cursor.fetchone()[0] == 4200
    cursor.execute("SELECT COUNT(*) FROM claims")
    assert cursor.fetchone()[0] == 4249



def test_portfolio_experience_calculation():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repo = LossExperienceRepository(data_dir)
    exp = repo.get_portfolio_experience("PF-01")
    assert exp is not None
    assert exp.portfolio_id == "PF-01"
    assert exp.total_policy_count == 953
    assert exp.total_claim_count == 337
    assert exp.total_earned_premium > 0
    assert exp.total_incurred_loss > 0
    assert 0 < exp.overall_loss_ratio < 1.0
    assert "flood" in exp.perils
    assert "storm" in exp.perils
    assert "fire" in exp.perils
    assert "hail" in exp.perils
    assert "subsidence" in exp.perils


def test_portfolio_filtering():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repo = LossExperienceRepository(data_dir)
    all_exp = repo.get_portfolio_experience("PF-01")
    filtered_exp = repo.get_portfolio_experience("PF-01", underwriting_year=2023)
    assert filtered_exp is not None
    assert filtered_exp.total_policy_count < all_exp.total_policy_count


def test_api_endpoints():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    with TestClient(app) as client:
        # 1. Health
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

        # 2. Valid portfolio
        res = client.get("/portfolios/PF-01/loss-experience")
        assert res.status_code == 200
        data = res.json()
        assert data["portfolio_id"] == "PF-01"
        assert "perils" in data
        assert "overall_loss_ratio" in data
        assert "largest_single_claim" in data

        # 3. Non-existent portfolio
        res = client.get("/portfolios/PF-999/loss-experience")
        assert res.status_code == 404

        # 4. Filtered portfolio
        res = client.get("/portfolios/PF-01/loss-experience?underwriting_year=2023&region=Syddanmark")
        assert res.status_code == 200

        # 5. Compare portfolios
        res = client.get("/portfolios/loss-experience?sort_by=loss_ratio&order=desc")
        assert res.status_code == 200
        portfolios = res.json()["portfolios"]
        assert len(portfolios) == 12
        # Verify descending order
        ratios = [p["overall_loss_ratio"] for p in portfolios]
        assert ratios == sorted(ratios, reverse=True)

        # 6. Data quality report
        res = client.get("/data-quality")
        assert res.status_code == 200
        dq = res.json()
        assert dq["quality_adjustments"]["orphaned_claims_excluded"] == 260

        # 7. Web UI
        res = client.get("/")
        assert res.status_code == 200
        assert "Envira Loss-Experience Reporting" in res.text


def test_independent_mathematical_reconciliation():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    from scripts.verify import run_verification
    assert run_verification(data_dir) is True

