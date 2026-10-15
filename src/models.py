"""Domain entities, data transfer objects, and constants for Envira Loss Experience."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Set

STANDARD_PERILS: Set[str] = {"fire", "flood", "hail", "storm", "subsidence"}

VALID_REGIONS: Set[str] = {
    "Hovedstaden",
    "Midtjylland",
    "Nordjylland",
    "Sjaelland",
    "Syddanmark",
}

VALID_ASSET_TYPES: Set[str] = {
    "agricultural",
    "commercial",
    "industrial",
    "public",
    "residential",
}

VALID_SORT_FIELDS: Set[str] = {
    "loss_ratio",
    "incurred_loss",
    "earned_premium",
    "policy_count",
    "claim_count",
    "portfolio_id",
}

VALID_SORT_ORDERS: Set[str] = {"asc", "desc"}


def parse_date(date_str: str) -> datetime:
    """Parse mixed date formats (ISO or European) to datetime object."""
    cleaned_date_str = date_str.strip()
    for date_format in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned_date_str, date_format)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


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
            "perils": {
                peril_name: peril_experience.to_dict()
                for peril_name, peril_experience in sorted(self.perils.items())
            },
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
