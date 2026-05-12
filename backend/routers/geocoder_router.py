from __future__ import annotations
from fastapi import APIRouter, Query
from geocoder import forward_search

router = APIRouter(prefix="/api/geocoder", tags=["geocoder"])


@router.get("/search")
def search_location(q: str = Query(..., min_length=3)):
    """Forward geocode a query string via Nominatim. Returns up to 5 candidates."""
    return forward_search(q)
