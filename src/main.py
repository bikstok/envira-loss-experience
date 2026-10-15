"""FastAPI service exposing loss experience and portfolio analytics endpoints."""

import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.repository import LossExperienceRepository
from src.validators import validate_filters, validate_sort_params

DATA_DIR = os.getenv("DATA_DIR", "data")
repo: Optional[LossExperienceRepository] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global repo
    if not os.path.isdir(DATA_DIR):
        raise RuntimeError(f"Data directory '{DATA_DIR}' does not exist.")
    repo = LossExperienceRepository(DATA_DIR)
    yield


app = FastAPI(
    title="Envira Loss-Experience Service",
    description="Underwriting loss experience analytics for Danish climate and property risk.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_repo() -> LossExperienceRepository:
    if repo is None:
        raise HTTPException(status_code=503, detail="Repository not initialized.")
    return repo


@app.get("/health", tags=["Health"])
def health_check():
    """Health check for service boot and container orchestration."""
    r = get_repo()
    return {
        "status": "healthy",
        "portfolios_loaded": len(r.get_portfolio_ids()),
        "policies_loaded": r.total_policies_count,
    }



@app.get(
    "/portfolios/{portfolio_id}/loss-experience",
    tags=["Loss Experience"],
    summary="Get loss experience for a specific portfolio",
)
def get_portfolio_loss_experience(
    portfolio_id: str,
    underwriting_year: Optional[int] = Query(None, description="Filter by policy inception year"),
    region: Optional[str] = Query(None, description="Filter by asset region"),
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
):
    """
    Returns loss experience broken down by peril:
    - policy_count
    - earned_premium (DKK)
    - incurred_loss (DKK)
    - loss_ratio
    - claim_count
    - largest_single_claim (DKK)
    """
    validate_filters(underwriting_year=underwriting_year, region=region, asset_type=asset_type)
    r = get_repo()
    exp = r.get_portfolio_experience(
        portfolio_id=portfolio_id,
        underwriting_year=underwriting_year,
        region=region,
        asset_type=asset_type,
    )
    if exp is None:
        valid_ids = ", ".join(r.get_portfolio_ids())
        raise HTTPException(
            status_code=404,
            detail=f"Portfolio '{portfolio_id}' not found. Valid portfolios: {valid_ids}",
        )
    return exp.to_dict()


@app.get(
    "/portfolios/loss-experience",
    tags=["Loss Experience"],
    summary="Compare all portfolios with ranking",
)
def compare_portfolios(
    sort_by: str = Query(
        "loss_ratio",
        description="Metric to sort by: loss_ratio, incurred_loss, earned_premium, policy_count, claim_count, portfolio_id",
    ),
    order: str = Query("desc", description="Sort order: desc or asc"),
    underwriting_year: Optional[int] = Query(None, description="Filter by policy inception year"),
    region: Optional[str] = Query(None, description="Filter by asset region"),
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
):
    """Returns comparative summary of all portfolios with configurable ranking."""
    validate_sort_params(sort_by, order)
    validate_filters(underwriting_year=underwriting_year, region=region, asset_type=asset_type)
    r = get_repo()
    portfolios = r.get_all_portfolios_experience(
        sort_by=sort_by,
        order=order,
        underwriting_year=underwriting_year,
        region=region,
        asset_type=asset_type,
    )
    return {
        "ranking_criteria": {"sort_by": sort_by, "order": order},
        "portfolios_count": len(portfolios),
        "portfolios": [
            {
                "portfolio_id": p.portfolio_id,
                "overall_loss_ratio": round(p.overall_loss_ratio, 4),
                "total_earned_premium_dkk": round(p.total_earned_premium, 2),
                "total_incurred_loss_dkk": round(p.total_incurred_loss, 2),
                "total_policy_count": p.total_policy_count,
                "total_claim_count": p.total_claim_count,
                "largest_single_claim_dkk": round(p.largest_single_claim, 2),
            }
            for p in portfolios
        ],
    }


@app.get("/data-quality", tags=["Data Quality"], summary="Data quality audit and exclusion report")
def get_data_quality():
    """Reports data cleaning, normalization, exclusions, and operational assumptions."""
    r = get_repo()
    return r.get_data_quality_report().to_dict()


TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


@app.get("/", response_class=HTMLResponse, tags=["UI"], summary="Web interface for non-technical users")
def web_ui():
    """Self-contained interactive dashboard for non-technical underwriters."""
    r = get_repo()
    portfolio_options = "".join(f'<option value="{p}">{p}</option>' for p in r.get_portfolio_ids())
    template_path = os.path.join(TEMPLATES_DIR, "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    return html.replace("{{ portfolio_options }}", portfolio_options)

