"""Input validation rules and HTTP 400 error handling for API endpoints."""

from typing import Optional
from fastapi import HTTPException

from src.models import (
    VALID_ASSET_TYPES,
    VALID_REGIONS,
    VALID_SORT_FIELDS,
    VALID_SORT_ORDERS,
)


def validate_filters(
    underwriting_year: Optional[int] = None,
    region: Optional[str] = None,
    asset_type: Optional[str] = None,
):
    """Validate query filters, raising HTTP 400 for invalid inputs."""
    if underwriting_year is not None:
        if underwriting_year < 1900 or underwriting_year > 2100:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid underwriting_year '{underwriting_year}'. Must be between 1900 and 2100.",
            )
    if region is not None and region not in VALID_REGIONS:
        allowed_options_display = ", ".join(sorted(VALID_REGIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid region '{region}'. Allowed regions: {allowed_options_display}",
        )
    if asset_type is not None and asset_type not in VALID_ASSET_TYPES:
        allowed_options_display = ", ".join(sorted(VALID_ASSET_TYPES))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid asset_type '{asset_type}'. Allowed asset types: {allowed_options_display}",
        )


def validate_sort_params(sort_by: str, order: str):
    """Validate sort field and direction parameters, raising HTTP 400 for invalid inputs."""
    if sort_by not in VALID_SORT_FIELDS:
        allowed_options_display = ", ".join(sorted(VALID_SORT_FIELDS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by field '{sort_by}'. Allowed fields: {allowed_options_display}",
        )
    if order.lower() not in VALID_SORT_ORDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort order '{order}'. Allowed orders: asc, desc",
        )
