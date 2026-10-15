"""Data access repository executing parameterized SQL aggregation queries."""

import sqlite3
from typing import Dict, List, Optional

from src.db import init_db, load_csv_data_to_sqlite
from src.models import (
    STANDARD_PERILS,
    DataQualityReport,
    PerilExperience,
    PortfolioExperience,
)


class LossExperienceRepository:
    """SQLite-backed repository and underwriting analytics engine."""

    def __init__(self, data_dir: str, db_path: str = ":memory:"):
        self.data_dir = data_dir
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        init_db(self.connection)
        load_csv_data_to_sqlite(self.connection, self.data_dir)

    @property
    def conn(self) -> sqlite3.Connection:
        """Backwards compatibility accessor for connection."""
        return self.connection

    @property
    def total_policies_count(self) -> int:
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM policies")
        return cursor.fetchone()[0]

    def get_portfolio_ids(self) -> List[str]:
        cursor = self.connection.cursor()
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
        cursor = self.connection.cursor()

        # Check portfolio existence
        cursor.execute("SELECT 1 FROM assets WHERE portfolio_id = ? LIMIT 1", (portfolio_id,))
        if not cursor.fetchone():
            return None

        # Build dynamic filter conditions
        filter_clauses = ["a.portfolio_id = ?"]
        query_parameters = [portfolio_id]

        if underwriting_year is not None:
            filter_clauses.append("p.underwriting_year = ?")
            query_parameters.append(underwriting_year)
        if region is not None:
            filter_clauses.append("a.region = ?")
            query_parameters.append(region)
        if asset_type is not None:
            filter_clauses.append("a.asset_type = ?")
            query_parameters.append(asset_type)

        filter_sql_condition = " AND ".join(filter_clauses)

        # 1. Query policy counts and earned premium per peril
        sql_policies = f"""
            SELECT
                p.peril,
                COUNT(p.policy_id) AS policy_count,
                COALESCE(SUM(p.earned_premium_dkk), 0.0) AS earned_premium
            FROM policies p
            JOIN assets a ON p.asset_id = a.asset_id
            WHERE {filter_sql_condition}
            GROUP BY p.peril;
        """
        cursor.execute(sql_policies, query_parameters)
        policy_rows = {
            row["peril"]: (row["policy_count"], row["earned_premium"])
            for row in cursor.fetchall()
        }

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
            WHERE {filter_sql_condition}
            GROUP BY p.peril;
        """
        cursor.execute(sql_claims, query_parameters)
        claim_rows = {
            row["peril"]: (
                row["claim_count"],
                row["incurred_loss"],
                row["largest_single_claim"],
            )
            for row in cursor.fetchall()
        }

        # Ensure all standard perils exist in the output
        all_perils = STANDARD_PERILS | set(policy_rows.keys()) | set(claim_rows.keys())

        perils: Dict[str, PerilExperience] = {}
        for peril in all_perils:
            peril_policy_count, peril_earned_premium = policy_rows.get(peril, (0, 0.0))
            peril_claim_count, peril_incurred_loss, peril_largest_claim = claim_rows.get(peril, (0, 0.0, 0.0))
            loss_ratio = (peril_incurred_loss / peril_earned_premium) if peril_earned_premium > 0 else 0.0
            perils[peril] = PerilExperience(
                peril=peril,
                policy_count=peril_policy_count,
                earned_premium=peril_earned_premium,
                incurred_loss=peril_incurred_loss,
                loss_ratio=loss_ratio,
                claim_count=peril_claim_count,
                largest_single_claim=max(0.0, peril_largest_claim),
            )

        total_policy_count = sum(peril_experience.policy_count for peril_experience in perils.values())
        total_earned_premium = sum(peril_experience.earned_premium for peril_experience in perils.values())
        total_incurred_loss = sum(peril_experience.incurred_loss for peril_experience in perils.values())
        total_claim_count = sum(peril_experience.claim_count for peril_experience in perils.values())
        largest_single_claim = max([peril_experience.largest_single_claim for peril_experience in perils.values()], default=0.0)
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
        for portfolio_id in self.get_portfolio_ids():
            portfolio_experience = self.get_portfolio_experience(
                portfolio_id=portfolio_id,
                underwriting_year=underwriting_year,
                region=region,
                asset_type=asset_type,
            )
            if portfolio_experience:
                portfolios.append(portfolio_experience)

        reverse = order.lower() == "desc"
        if sort_by == "loss_ratio":
            portfolios.sort(key=lambda portfolio: portfolio.overall_loss_ratio, reverse=reverse)
        elif sort_by == "incurred_loss":
            portfolios.sort(key=lambda portfolio: portfolio.total_incurred_loss, reverse=reverse)
        elif sort_by == "earned_premium":
            portfolios.sort(key=lambda portfolio: portfolio.total_earned_premium, reverse=reverse)
        elif sort_by == "policy_count":
            portfolios.sort(key=lambda portfolio: portfolio.total_policy_count, reverse=reverse)
        elif sort_by == "claim_count":
            portfolios.sort(key=lambda portfolio: portfolio.total_claim_count, reverse=reverse)
        else:
            portfolios.sort(key=lambda portfolio: portfolio.portfolio_id)

        return portfolios

    def get_data_quality_report(self) -> DataQualityReport:
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_assets = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM policies")
        total_policies = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM claims")
        loaded_claims = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fx_rates")
        total_fx_rates_count = cursor.fetchone()[0]

        cursor.execute("SELECT metric_key, metric_value FROM data_quality_metrics")
        data_quality_metrics = dict(cursor.fetchall())

        orphaned_claims_count = data_quality_metrics.get("orphaned_claims_excluded", 0)

        return DataQualityReport(
            total_assets=total_assets,
            total_policies=total_policies,
            total_claims=loaded_claims + orphaned_claims_count,
            total_fx_rates=total_fx_rates_count,
            orphaned_claims_excluded=orphaned_claims_count,
            claims_loss_before_inception=data_quality_metrics.get("claims_loss_before_inception_retained", 0),
            negative_paid_claims=data_quality_metrics.get("negative_paid_claims_retained", 0),
            non_standard_peril_casing_fixed=data_quality_metrics.get("non_standard_perils_normalized", 0),
            european_date_formats_parsed=data_quality_metrics.get("european_dates_parsed", 0),
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
