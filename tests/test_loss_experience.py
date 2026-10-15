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
    peril_experience = PerilExperience(
        peril="storm",
        policy_count=10,
        earned_premium=100000.0,
        incurred_loss=60000.0,
        claim_count=3,
        largest_single_claim=30000.0,
    )
    peril_experience.loss_ratio = peril_experience.incurred_loss / peril_experience.earned_premium
    peril_dict = peril_experience.to_dict()
    assert peril_dict["loss_ratio"] == 0.6
    assert peril_dict["earned_premium"] == 100000.0
    assert peril_dict["incurred_loss"] == 60000.0


def test_repository_loading():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repository = LossExperienceRepository(data_dir)
    data_quality = repository.get_data_quality_report()
    assert data_quality.total_assets == 4200
    assert data_quality.total_policies == 11560
    assert data_quality.orphaned_claims_excluded == 260
    assert data_quality.claims_loss_before_inception == 310
    assert data_quality.negative_paid_claims == 262
    assert len(repository.get_portfolio_ids()) == 12
    assert repository.total_policies_count == 11560


def test_sqlite_direct_query():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repository = LossExperienceRepository(data_dir)
    cursor = repository.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM assets")
    assert cursor.fetchone()[0] == 4200
    cursor.execute("SELECT COUNT(*) FROM claims")
    assert cursor.fetchone()[0] == 4249



def test_portfolio_experience_calculation():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repository = LossExperienceRepository(data_dir)
    portfolio_experience = repository.get_portfolio_experience("PF-01")
    assert portfolio_experience is not None
    assert portfolio_experience.portfolio_id == "PF-01"
    assert portfolio_experience.total_policy_count == 953
    assert portfolio_experience.total_claim_count == 337
    assert portfolio_experience.total_earned_premium > 0
    assert portfolio_experience.total_incurred_loss > 0
    assert 0 < portfolio_experience.overall_loss_ratio < 1.0
    assert "flood" in portfolio_experience.perils
    assert "storm" in portfolio_experience.perils
    assert "fire" in portfolio_experience.perils
    assert "hail" in portfolio_experience.perils
    assert "subsidence" in portfolio_experience.perils


def test_portfolio_filtering():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    repository = LossExperienceRepository(data_dir)
    all_years_experience = repository.get_portfolio_experience("PF-01")
    filtered_portfolio_experience = repository.get_portfolio_experience("PF-01", underwriting_year=2023)
    assert filtered_portfolio_experience is not None
    assert filtered_portfolio_experience.total_policy_count < all_years_experience.total_policy_count


def test_api_endpoints():
    data_dir = os.getenv("DATA_DIR", "data")
    if not os.path.exists(data_dir):
        pytest.skip("Data directory not present")

    with TestClient(app) as client:
        # 1. Health
        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "healthy"

        # 2. Valid portfolio
        portfolio_response = client.get("/portfolios/PF-01/loss-experience")
        assert portfolio_response.status_code == 200
        portfolio_data = portfolio_response.json()
        assert portfolio_data["portfolio_id"] == "PF-01"
        assert "perils" in portfolio_data
        assert "overall_loss_ratio" in portfolio_data
        assert "largest_single_claim" in portfolio_data

        # 3. Non-existent portfolio
        not_found_response = client.get("/portfolios/PF-999/loss-experience")
        assert not_found_response.status_code == 404

        # 4. Filtered portfolio (valid)
        filtered_response = client.get("/portfolios/PF-01/loss-experience?underwriting_year=2023&region=Syddanmark")
        assert filtered_response.status_code == 200

        # 4b. Filter validation (invalid inputs -> 400)
        bad_year_response = client.get("/portfolios/PF-01/loss-experience?underwriting_year=1800")
        assert bad_year_response.status_code == 400
        assert "underwriting_year" in bad_year_response.json()["detail"]

        bad_region_response = client.get("/portfolios/PF-01/loss-experience?region=Atlantis")
        assert bad_region_response.status_code == 400
        assert "region" in bad_region_response.json()["detail"]

        bad_type_response = client.get("/portfolios/PF-01/loss-experience?asset_type=spaceship")
        assert bad_type_response.status_code == 400
        assert "asset_type" in bad_type_response.json()["detail"]

        # 5. Compare portfolios (valid)
        compare_response = client.get("/portfolios/loss-experience?sort_by=loss_ratio&order=desc")
        assert compare_response.status_code == 200
        portfolios = compare_response.json()["portfolios"]
        assert len(portfolios) == 12
        # Verify descending order
        loss_ratios = [portfolio["overall_loss_ratio"] for portfolio in portfolios]
        assert loss_ratios == sorted(loss_ratios, reverse=True)

        # 5b. Compare portfolios validation (invalid inputs -> 400)
        bad_sort_response = client.get("/portfolios/loss-experience?sort_by=random_column")
        assert bad_sort_response.status_code == 400
        assert "sort_by" in bad_sort_response.json()["detail"]

        bad_order_response = client.get("/portfolios/loss-experience?order=backwards")
        assert bad_order_response.status_code == 400
        assert "order" in bad_order_response.json()["detail"]

        # 6. Data quality report
        data_quality_response = client.get("/data-quality")
        assert data_quality_response.status_code == 200
        data_quality_data = data_quality_response.json()
        assert data_quality_data["quality_adjustments"]["orphaned_claims_excluded"] == 260

        # 7. Web UI
        ui_response = client.get("/")
        assert ui_response.status_code == 200
        assert "Envira Loss-Experience Reporting" in ui_response.text

