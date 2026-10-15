"""Core domain models, data ingestion, and loss experience calculation logic."""

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple


def parse_date(date_str: str) -> datetime:
    """Parse dates supporting both ISO (YYYY-MM-DD) and European (DD-MM-YYYY) formats."""
    clean_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(clean_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


@dataclass(frozen=True)
class Asset:
    asset_id: str
    portfolio_id: str
    region: str
    asset_type: str
    construction_year: int
    sum_insured_dkk: float


@dataclass(frozen=True)
class Policy:
    policy_id: str
    asset_id: str
    peril: str
    inception_date: datetime
    expiry_date: datetime
    annual_premium: float
    currency: str
    underwriting_year: int
    earned_premium_dkk: float


@dataclass(frozen=True)
class Claim:
    claim_id: str
    policy_id: str
    loss_date: datetime
    reported_date: datetime
    paid_amount: float
    reserve_amount: float
    currency: str
    status: str
    incurred_loss_dkk: float


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
    """In-memory loaded data repository and analytics engine."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.assets: Dict[str, Asset] = {}
        self.policies: Dict[str, Policy] = {}
        self.claims: List[Claim] = []
        self.fx_rates: Dict[Tuple[str, str], float] = {}

        # Quality metrics tracking
        self.orphaned_claims_excluded = 0
        self.claims_loss_before_inception = 0
        self.negative_paid_claims = 0
        self.non_standard_perils_fixed = 0
        self.european_dates_parsed = 0

        self._load_data()

    def _get_fx_rate(self, dt: datetime, currency: str) -> float:
        if currency == "DKK":
            return 1.0
        month_key = dt.strftime("%Y-%m")
        rate = self.fx_rates.get((month_key, currency))
        if rate is None:
            raise KeyError(f"Missing FX rate for month {month_key} and currency {currency}")
        return rate

    def _load_data(self):
        # 1. Load FX Rates
        fx_path = os.path.join(self.data_dir, "fx_rates.csv")
        with open(fx_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month = row["month"].strip()
                curr = row["currency"].strip()
                rate = float(row["rate_dkk_per_unit"])
                self.fx_rates[(month, curr)] = rate

        # 2. Load Assets
        assets_path = os.path.join(self.data_dir, "assets.csv")
        with open(assets_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                asset = Asset(
                    asset_id=row["asset_id"].strip(),
                    portfolio_id=row["portfolio_id"].strip(),
                    region=row["region"].strip(),
                    asset_type=row["asset_type"].strip(),
                    construction_year=int(row["construction_year"]),
                    sum_insured_dkk=float(row["sum_insured_dkk"]),
                )
                self.assets[asset.asset_id] = asset

        # 3. Load Policies
        policies_path = os.path.join(self.data_dir, "policies.csv")
        with open(policies_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_peril = row["peril"]
                normalized_peril = raw_peril.strip().lower()
                if raw_peril != normalized_peril:
                    self.non_standard_perils_fixed += 1

                inc_raw = row["inception_date"].strip()
                if "-" in inc_raw and inc_raw[2] == "-":
                    self.european_dates_parsed += 1
                inception = parse_date(inc_raw)

                exp_raw = row["expiry_date"].strip()
                if "-" in exp_raw and exp_raw[2] == "-":
                    self.european_dates_parsed += 1
                expiry = parse_date(exp_raw)

                curr = row["currency"].strip()
                annual_prem = float(row["annual_premium"])
                fx_rate = self._get_fx_rate(inception, curr)
                earned_prem_dkk = annual_prem * fx_rate

                policy = Policy(
                    policy_id=row["policy_id"].strip(),
                    asset_id=row["asset_id"].strip(),
                    peril=normalized_peril,
                    inception_date=inception,
                    expiry_date=expiry,
                    annual_premium=annual_prem,
                    currency=curr,
                    underwriting_year=inception.year,
                    earned_premium_dkk=earned_prem_dkk,
                )
                self.policies[policy.policy_id] = policy

        # 4. Load Claims
        claims_path = os.path.join(self.data_dir, "claims.csv")
        with open(claims_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pol_id = row["policy_id"].strip()
                if pol_id not in self.policies:
                    # Orphaned claim: cannot link to any asset, peril or portfolio
                    self.orphaned_claims_excluded += 1
                    continue

                policy = self.policies[pol_id]

                loss_raw = row["loss_date"].strip()
                if "-" in loss_raw and loss_raw[2] == "-":
                    self.european_dates_parsed += 1
                loss_date = parse_date(loss_raw)

                rep_raw = row["reported_date"].strip()
                if "-" in rep_raw and rep_raw[2] == "-":
                    self.european_dates_parsed += 1
                reported_date = parse_date(rep_raw)

                if loss_date < policy.inception_date:
                    self.claims_loss_before_inception += 1

                paid = float(row["paid_amount"])
                res = float(row["reserve_amount"])
                if paid < 0 or res < 0:
                    self.negative_paid_claims += 1

                curr = row["currency"].strip()
                status = row["status"].strip().lower()

                # Incurred loss calculation per brief definitions:
                # - withdrawn / declined: 0.0
                # - settled: paid_amount
                # - open: paid_amount + reserve_amount
                if status in ("withdrawn", "declined"):
                    incurred_orig = 0.0
                elif status == "settled":
                    incurred_orig = paid
                elif status == "open":
                    incurred_orig = paid + res
                else:
                    incurred_orig = paid + res

                fx_rate = self._get_fx_rate(loss_date, curr)
                incurred_dkk = incurred_orig * fx_rate

                claim = Claim(
                    claim_id=row["claim_id"].strip(),
                    policy_id=pol_id,
                    loss_date=loss_date,
                    reported_date=reported_date,
                    paid_amount=paid,
                    reserve_amount=res,
                    currency=curr,
                    status=status,
                    incurred_loss_dkk=incurred_dkk,
                )
                self.claims.append(claim)

    def get_portfolio_ids(self) -> List[str]:
        return sorted({a.portfolio_id for a in self.assets.values()})

    def get_portfolio_experience(
        self,
        portfolio_id: str,
        underwriting_year: Optional[int] = None,
        region: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Optional[PortfolioExperience]:
        """Compute loss experience by peril and overall for a portfolio."""
        # Check if portfolio exists
        portfolio_exists = any(a.portfolio_id == portfolio_id for a in self.assets.values())
        if not portfolio_exists:
            return None

        # Filter policies belonging to this portfolio
        matching_policies: Dict[str, Policy] = {}
        for pol_id, policy in self.policies.items():
            asset = self.assets[policy.asset_id]
            if asset.portfolio_id != portfolio_id:
                continue
            if underwriting_year is not None and policy.underwriting_year != underwriting_year:
                continue
            if region is not None and asset.region != region:
                continue
            if asset_type is not None and asset.asset_type != asset_type:
                continue
            matching_policies[pol_id] = policy

        # Find matching claims belonging to these policies
        matching_claims = [c for c in self.claims if c.policy_id in matching_policies]

        # Group by peril
        perils: Dict[str, PerilExperience] = {}
        # Ensure all standard perils are present in the response
        standard_perils = {"fire", "flood", "hail", "storm", "subsidence"}
        for peril in standard_perils:
            perils[peril] = PerilExperience(peril=peril)

        # Aggregate policies
        for policy in matching_policies.values():
            if policy.peril not in perils:
                perils[policy.peril] = PerilExperience(peril=policy.peril)
            exp = perils[policy.peril]
            exp.policy_count += 1
            exp.earned_premium += policy.earned_premium_dkk

        # Aggregate claims
        for claim in matching_claims:
            policy = matching_policies[claim.policy_id]
            exp = perils[policy.peril]
            exp.claim_count += 1
            exp.incurred_loss += claim.incurred_loss_dkk
            if claim.incurred_loss_dkk > exp.largest_single_claim:
                exp.largest_single_claim = claim.incurred_loss_dkk

        # Calculate loss ratios and totals
        total_policy_count = sum(p.policy_count for p in perils.values())
        total_earned_premium = sum(p.earned_premium for p in perils.values())
        total_incurred_loss = sum(p.incurred_loss for p in perils.values())
        total_claim_count = sum(p.claim_count for p in perils.values())
        largest_single_claim = max(
            [c.incurred_loss_dkk for c in matching_claims],
            default=0.0,
        )

        for exp in perils.values():
            if exp.earned_premium > 0:
                exp.loss_ratio = exp.incurred_loss / exp.earned_premium
            else:
                exp.loss_ratio = 0.0

        overall_loss_ratio = (
            total_incurred_loss / total_earned_premium if total_earned_premium > 0 else 0.0
        )

        return PortfolioExperience(
            portfolio_id=portfolio_id,
            perils=perils,
            total_policy_count=total_policy_count,
            total_earned_premium=total_earned_premium,
            total_incurred_loss=total_incurred_loss,
            overall_loss_ratio=overall_loss_ratio,
            total_claim_count=total_claim_count,
            largest_single_claim=max(0.0, largest_single_claim),
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
        fx_count = len(self.fx_rates)
        return DataQualityReport(
            total_assets=len(self.assets),
            total_policies=len(self.policies),
            total_claims=len(self.claims) + self.orphaned_claims_excluded,
            total_fx_rates=fx_count,
            orphaned_claims_excluded=self.orphaned_claims_excluded,
            claims_loss_before_inception=self.claims_loss_before_inception,
            negative_paid_claims=self.negative_paid_claims,
            non_standard_peril_casing_fixed=self.non_standard_perils_fixed,
            european_date_formats_parsed=self.european_dates_parsed,
            known_portfolios=self.get_portfolio_ids(),
            assumptions_summary=[
                "Orphaned claims (260 rows referencing non-existent policy_ids) were excluded from portfolio calculations because they cannot be attributed to any portfolio or peril.",
                "Non-standard peril values (mixed case, leading/trailing whitespace) were normalized to standard lowercase perils (fire, flood, hail, storm, subsidence).",
                "European date formats (DD-MM-YYYY) in claims and policies were parsed alongside ISO format (YYYY-MM-DD).",
                "Claims with loss dates occurring prior to policy inception (310 rows) were retained under their assigned policy_id per the brief definition ('A claim belongs to a policy').",
                "Negative paid amounts (262 settled claims) were treated as negative incurred loss (representing subrogation/salvage recoveries), consistent with insurance accounting.",
                "FX conversion uses the month of policy inception for earned premium, and the month of loss date for claim incurred losses.",
            ],
        )
