"""FastAPI service exposing loss experience and portfolio analytics endpoints."""

import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.domain import LossExperienceRepository

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


@app.get("/", response_class=HTMLResponse, tags=["UI"], summary="Web interface for non-technical users")
def web_ui():
    """Self-contained interactive dashboard for non-technical underwriters."""
    r = get_repo()
    portfolio_options = "".join(f'<option value="{p}">{p}</option>' for p in r.get_portfolio_ids())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Envira | Loss Experience Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #f8fafc;
            color: #0f172a;
            margin: 0;
            padding: 32px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            padding: 32px;
        }}
        h1 {{
            margin-top: 0;
            color: #1e293b;
            font-size: 26px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .controls {{
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            align-items: center;
            margin-bottom: 24px;
            padding: 16px;
            background: #f1f5f9;
            border-radius: 8px;
        }}
        label {{
            font-weight: 600;
            font-size: 14px;
            color: #475569;
        }}
        select, button {{
            padding: 8px 12px;
            font-size: 14px;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            background: white;
        }}
        button {{
            background: #0284c7;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 600;
        }}
        button:hover {{
            background: #0369a1;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            text-align: right;
            padding: 12px 16px;
            border-bottom: 1px solid #e2e8f0;
        }}
        th:first-child, td:first-child {{
            text-align: left;
        }}
        th {{
            background: #f8fafc;
            color: #64748b;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        tr:hover {{
            background: #f8fafc;
        }}
        .total-row {{
            font-weight: 700;
            background: #f1f5f9;
            border-top: 2px solid #cbd5e1;
        }}
        .badge {{
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 13px;
        }}
        .badge-good {{ background: #dcfce7; color: #166534; }}
        .badge-warning {{ background: #fef9c3; color: #854d0e; }}
        .badge-bad {{ background: #fee2e2; color: #991b1b; }}
        .meta-card {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .metric-box {{
            padding: 16px;
            background: #f8fafc;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}
        .metric-label {{ font-size: 12px; color: #64748b; text-transform: uppercase; }}
        .metric-value {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
        .footer {{
            margin-top: 32px;
            font-size: 13px;
            color: #94a3b8;
            display: flex;
            justify-content: space-between;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Envira Loss-Experience Reporting</h1>
        <p style="color: #64748b; margin-top: -8px;">Underwriting performance analytics across Danish property portfolios.</p>

        <div class="controls">
            <label for="portfolioSelect">Portfolio:</label>
            <select id="portfolioSelect">
                {portfolio_options}
            </select>

            <label for="yearFilter">Underwriting Year:</label>
            <select id="yearFilter">
                <option value="">All Years</option>
                <option value="2022">2022</option>
                <option value="2023">2023</option>
                <option value="2024">2024</option>
            </select>

            <label for="regionFilter">Region:</label>
            <select id="regionFilter">
                <option value="">All Regions</option>
                <option value="Hovedstaden">Hovedstaden</option>
                <option value="Midtjylland">Midtjylland</option>
                <option value="Nordjylland">Nordjylland</option>
                <option value="Sjaelland">Sjaelland</option>
                <option value="Syddanmark">Syddanmark</option>
            </select>

            <label for="assetTypeFilter">Asset Type:</label>
            <select id="assetTypeFilter">
                <option value="">All Asset Types</option>
                <option value="agricultural">Agricultural</option>
                <option value="commercial">Commercial</option>
                <option value="industrial">Industrial</option>
                <option value="public">Public</option>
                <option value="residential">Residential</option>
            </select>

            <button onclick="fetchExperience()">Update View</button>
        </div>

        <div class="meta-card" id="summaryCard"></div>

        <table id="experienceTable">
            <thead>
                <tr>
                    <th>Peril</th>
                    <th>Policies</th>
                    <th>Claims</th>
                    <th>Earned Premium</th>
                    <th>Incurred Loss</th>
                    <th>Loss Ratio</th>
                    <th>Largest Claim</th>
                </tr>
            </thead>
            <tbody id="tableBody">
                <tr><td colspan="7" style="text-align: center; color: #94a3b8;">Loading data...</td></tr>
            </tbody>
        </table>

        <div class="footer">
            <span>API Endpoints: <a href="/docs" target="_blank">Swagger Documentation</a> | <a href="/data-quality" target="_blank">Data Quality Report</a></span>
            <span>All figures in Danish Krone (DKK)</span>
        </div>
    </div>

    <script>
        function formatDKK(val) {{
            return new Intl.NumberFormat('da-DK', {{ style: 'currency', currency: 'DKK', maximumFractionDigits: 0 }}).format(val);
        }}

        function getLossBadge(ratio) {{
            let cls = ratio <= 0.60 ? 'badge-good' : (ratio <= 0.85 ? 'badge-warning' : 'badge-bad');
            return `<span class="badge ${{cls}}">${{(ratio * 100).toFixed(1)}}%</span>`;
        }}

        async function fetchExperience() {{
            const portfolio = document.getElementById('portfolioSelect').value;
            const year = document.getElementById('yearFilter').value;
            const region = document.getElementById('regionFilter').value;
            const assetType = document.getElementById('assetTypeFilter').value;

            let url = `/portfolios/${{portfolio}}/loss-experience?`;
            if (year) url += `underwriting_year=${{year}}&`;
            if (region) url += `region=${{encodeURIComponent(region)}}&`;
            if (assetType) url += `asset_type=${{encodeURIComponent(assetType)}}&`;

            try {{
                const res = await fetch(url);
                if (!res.ok) throw new Error('Failed to load portfolio data');
                const data = await res.json();

                // Summary boxes
                document.getElementById('summaryCard').innerHTML = `
                    <div class="metric-box">
                        <div class="metric-label">Overall Loss Ratio</div>
                        <div class="metric-value">${{getLossBadge(data.overall_loss_ratio)}}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Earned Premium</div>
                        <div class="metric-value">${{formatDKK(data.total_earned_premium)}}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Incurred Loss</div>
                        <div class="metric-value">${{formatDKK(data.total_incurred_loss)}}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Total Policies</div>
                        <div class="metric-value">${{data.total_policy_count.toLocaleString()}}</div>
                    </div>
                `;

                let rowsHtml = '';
                for (const [peril, exp] of Object.entries(data.perils)) {{
                    rowsHtml += `
                        <tr>
                            <td><strong>${{peril.charAt(0).toUpperCase() + peril.slice(1)}}</strong></td>
                            <td>${{exp.policy_count.toLocaleString()}}</td>
                            <td>${{exp.claim_count.toLocaleString()}}</td>
                            <td>${{formatDKK(exp.earned_premium)}}</td>
                            <td>${{formatDKK(exp.incurred_loss)}}</td>
                            <td>${{getLossBadge(exp.loss_ratio)}}</td>
                            <td>${{formatDKK(exp.largest_single_claim)}}</td>
                        </tr>
                    `;
                }}

                rowsHtml += `
                    <tr class="total-row">
                        <td>Total</td>
                        <td>${{data.total_policy_count.toLocaleString()}}</td>
                        <td>${{data.total_claim_count.toLocaleString()}}</td>
                        <td>${{formatDKK(data.total_earned_premium)}}</td>
                        <td>${{formatDKK(data.total_incurred_loss)}}</td>
                        <td>${{getLossBadge(data.overall_loss_ratio)}}</td>
                        <td>${{formatDKK(data.largest_single_claim)}}</td>
                    </tr>
                `;

                document.getElementById('tableBody').innerHTML = rowsHtml;
            }} catch (err) {{
                document.getElementById('tableBody').innerHTML = `<tr><td colspan="7" style="color: red; text-align: center;">Error loading data: ${{err.message}}</td></tr>`;
            }}
        }}

        // Initial load
        window.onload = fetchExperience;
    </script>
</body>
</html>"""
