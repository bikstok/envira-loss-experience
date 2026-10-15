"""Core domain models and SQLite-backed loss experience repository."""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.db import init_db, load_csv_data_to_sqlite, parse_date_to_iso


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime object."""
    return datetime.strptime(parse_date_to_iso(date_str), "%Y-%m-%d")


@dataclass
class PerilExperience:
    peril: str
    policy_count: int = 0
    earned_premium: float = 0.0
    incurred_loss: float = 0.0
    loss_ratio: float = 0.0
    claim_count: int = 0
    largest_single_claim: float = 0.0

    def to_dict(self) -> dict:
        return {
            "peril": self.peril,
            "policy_count": self.policy_count,
            "earned_premium": round(self.earned_premium, 2),
            "incurred_loss": round(self.incurred_loss, 2),
            "loss_ratio": round(self.loss_ratio, 4),
            "claim_count": self.claim_count,
            "largest_single_claim": round(self.largest_single_claim, 2),
        }


@dataclass
class PortfolioExperience:
    portfolio_id: str
    perils: Dict[str, PerilExperience] = field(default_factory=dict)
    total_policy_count: int = 0
    total_earned_premium: float = 0.0
    total_incurred_loss: float = 0.0
    overall_loss_ratio: float = 0.0
    total_claim_count: int = 0
    largest_single_claim: float = 0.0

    def to_dict(self) -> dict:
        return {
            "portfolio_id": self.portfolio_id,
            "total_policy_count": self.total_policy_count,
            "total_earned_premium": round(self.total_earned_premium, 2),
            "total_incurred_loss": round(self.total_incurred_loss, 2),
            "overall_loss_ratio": round(self.overall_loss_ratio, 4),
            "total_claim_count": self.total_claim_count,
            "largest_single_claim": round(self.largest_single_claim, 2),
            "perils": {p: exp.to_dict() for p, exp in sorted(self.perils.items())},
        }


@dataclass
class DataQualityReport:
    total_assets: int
    total_policies: int
    total_claims: int
    total_fx_rates: int
    orphaned_claims_excluded: int
    claims_loss_before_inception: int
    negative_paid_claims: int
    non_standard_peril_casing_fixed: int
    european_date_formats_parsed: int
    known_portfolios: List[str]
    assumptions_summary: List[str]

    def to_dict(self) -> dict:
        return {
            "dataset_counts": {
                "assets": self.total_assets,
                "policies": self.total_policies,
                "claims": self.total_claims,
                "fx_rates": self.total_fx_rates,
            },
            "quality_adjustments": {
                "orphaned_claims_excluded": self.orphaned_claims_excluded,
                "claims_loss_before_inception_retained": self.claims_loss_before_inception,
                "negative_paid_claims_retained_as_recoveries": self.negative_paid_claims,
                "non_standard_peril_values_normalized": self.non_standard_peril_casing_fixed,
                "european_dates_parsed": self.european_date_formats_parsed,
            },
            "known_portfolios": self.known_portfolios,
            "assumptions_summary": self.assumptions_summary,
        }


class LossExperienceRepository:
    """SQLite-backed repository and analytics engine."""

    def __init__(self, data_dir: str, db_path: str = ":memory:"):
        self.data_dir = data_dir
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        load_csv_data_to_sqlite(self.conn, self.data_dir)

    @property
    def total_policies_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM policies")
        return cursor.fetchone()[0]

    def get_portfolio_ids(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT portfolio_id FROM assets ORDER BY portfolio_id")
        return [row[0] for row in cursor.fetchall()]

    def get_portfolio_experience(
        self,
        portfolio_id: str,
        underwriting_year: Optional[int] = None,
        region: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Optional[PortfolioExperience]:
        """Compute loss experience by peril and overall using parameterized SQL queries."""
        cursor = self.conn.cursor()

        # Check portfolio existence
        cursor.execute("SELECT 1 FROM assets WHERE portfolio_id = ? LIMIT 1", (portfolio_id,))
        if not cursor.fetchone():
            return None

        # Build dynamic filter conditions
        where_clauses = ["a.portfolio_id = ?"]
        params = [portfolio_id]

        if underwriting_year is not None:
            where_clauses.append("p.underwriting_year = ?")
            params.append(underwriting_year)
        if region is not None:
            where_clauses.append("a.region = ?")
            params.append(region)
        if asset_type is not None:
            where_clauses.append("a.asset_type = ?")
            params.append(asset_type)

        where_sql = " AND ".join(where_clauses)

        # 1. Query policy counts and earned premium per peril
        sql_policies = f"""
            SELECT
                p.peril,
                COUNT(p.policy_id) AS policy_count,
                COALESCE(SUM(p.earned_premium_dkk), 0.0) AS earned_premium
            FROM policies p
            JOIN assets a ON p.asset_id = a.asset_id
            WHERE {where_sql}
            GROUP BY p.peril;
        """
        cursor.execute(sql_policies, params)
        policy_rows = {row["peril"]: (row["policy_count"], row["earned_premium"]) for row in cursor.fetchall()}

        # 2. Query claim counts, incurred losses, and largest claim per peril
        sql_claims = f"""
            SELECT
                p.peril,
                COUNT(c.claim_id) AS claim_count,
                COALESCE(SUM(c.incurred_loss_dkk), 0.0) AS incurred_loss,
                COALESCE(MAX(c.incurred_loss_dkk), 0.0) AS largest_single_claim
            FROM claims c
            JOIN policies p ON c.policy_id = p.policy_id
            JOIN assets a ON p.asset_id = a.asset_id
            WHERE {where_sql}
            GROUP BY p.peril;
        """
        cursor.execute(sql_claims, params)
        claim_rows = {
            row["peril"]: (
                row["claim_count"],
                row["incurred_loss"],
                row["largest_single_claim"],
            )
            for row in cursor.fetchall()
        }

        # Ensure all standard perils exist in the output
        standard_perils = {"fire", "flood", "hail", "storm", "subsidence"}
        all_perils = standard_perils | set(policy_rows.keys()) | set(claim_rows.keys())

        perils: Dict[str, PerilExperience] = {}
        for peril in all_perils:
            pol_count, prem = policy_rows.get(peril, (0, 0.0))
            clm_count, loss, max_claim = claim_rows.get(peril, (0, 0.0, 0.0))
            loss_ratio = (loss / prem) if prem > 0 else 0.0
            perils[peril] = PerilExperience(
                peril=peril,
                policy_count=pol_count,
                earned_premium=prem,
                incurred_loss=loss,
                loss_ratio=loss_ratio,
                claim_count=clm_count,
                largest_single_claim=max(0.0, max_claim),
            )

        total_policy_count = sum(p.policy_count for p in perils.values())
        total_earned_premium = sum(p.earned_premium for p in perils.values())
        total_incurred_loss = sum(p.incurred_loss for p in perils.values())
        total_claim_count = sum(p.claim_count for p in perils.values())
        largest_single_claim = max([p.largest_single_claim for p in perils.values()], default=0.0)
        overall_loss_ratio = (
            (total_incurred_loss / total_earned_premium) if total_earned_premium > 0 else 0.0
        )

        return PortfolioExperience(
            portfolio_id=portfolio_id,
            perils=perils,
            total_policy_count=total_policy_count,
            total_earned_premium=total_earned_premium,
            total_incurred_loss=total_incurred_loss,
            overall_loss_ratio=overall_loss_ratio,
            total_claim_count=total_claim_count,
            largest_single_claim=largest_single_claim,
        )

    def get_all_portfolios_experience(
        self,
        sort_by: str = "loss_ratio",
        order: str = "desc",
        underwriting_year: Optional[int] = None,
        region: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> List[PortfolioExperience]:
        """Compare all portfolios with configurable ranking."""
        portfolios = []
        for pid in self.get_portfolio_ids():
            exp = self.get_portfolio_experience(
                portfolio_id=pid,
                underwriting_year=underwriting_year,
                region=region,
                asset_type=asset_type,
            )
            if exp:
                portfolios.append(exp)

        reverse = order.lower() == "desc"
        if sort_by == "loss_ratio":
            portfolios.sort(key=lambda x: x.overall_loss_ratio, reverse=reverse)
        elif sort_by == "incurred_loss":
            portfolios.sort(key=lambda x: x.total_incurred_loss, reverse=reverse)
        elif sort_by == "earned_premium":
            portfolios.sort(key=lambda x: x.total_earned_premium, reverse=reverse)
        elif sort_by == "policy_count":
            portfolios.sort(key=lambda x: x.total_policy_count, reverse=reverse)
        elif sort_by == "claim_count":
            portfolios.sort(key=lambda x: x.total_claim_count, reverse=reverse)
        else:
            portfolios.sort(key=lambda x: x.portfolio_id)

        return portfolios

    def get_data_quality_report(self) -> DataQualityReport:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_assets = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM policies")
        total_policies = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM claims")
        loaded_claims = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fx_rates")
        total_fx = cursor.fetchone()[0]

        cursor.execute("SELECT metric_key, metric_value FROM data_quality_metrics")
        metrics = dict(cursor.fetchall())

        orphaned = metrics.get("orphaned_claims_excluded", 0)

        return DataQualityReport(
            total_assets=total_assets,
            total_policies=total_policies,
            total_claims=loaded_claims + orphaned,
            total_fx_rates=total_fx,
            orphaned_claims_excluded=orphaned,
            claims_loss_before_inception=metrics.get("claims_loss_before_inception_retained", 0),
            negative_paid_claims=metrics.get("negative_paid_claims_retained", 0),
            non_standard_peril_casing_fixed=metrics.get("non_standard_perils_normalized", 0),
            european_date_formats_parsed=metrics.get("european_dates_parsed", 0),
            known_portfolios=self.get_portfolio_ids(),
            assumptions_summary=[
                "Orphaned claims (260 rows referencing non-existent policy_ids) were excluded from portfolio calculations because they cannot be attributed to any portfolio or peril.",
                "Non-standard peril values (mixed case, leading/trailing whitespace) were normalized to standard lowercase perils (fire, flood, hail, storm, subsidence).",
                "European date formats (DD-MM-YYYY) in claims and policies were parsed into standard ISO format (YYYY-MM-DD).",
                "Claims with loss dates occurring prior to policy inception (310 rows) were retained under their assigned policy_id per the brief definition ('A claim belongs to a policy').",
                "Negative paid amounts (262 settled claims) were treated as negative incurred loss (representing subrogation/salvage recoveries), consistent with insurance accounting.",
                "FX conversion uses the month of policy inception for earned premium, and the month of loss date for claim incurred losses.",
            ],
        )
