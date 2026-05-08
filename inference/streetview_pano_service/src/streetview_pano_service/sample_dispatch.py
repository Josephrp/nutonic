"""Choose Google Street View vs synthetic stub frames."""

from __future__ import annotations

from fastapi import HTTPException

from streetview_pano_service.errors import StreetViewInsufficientCoverageError, StreetViewMetadataError
from streetview_pano_service.google_sample import sample_panos_google
from streetview_pano_service.models import PanosSampleRequest, PanosSampleResponse
from streetview_pano_service.pano_config import get_pano_settings
from streetview_pano_service.sample_frames import sample_panos_stub


def sample_panos(req: PanosSampleRequest) -> PanosSampleResponse:
    s = get_pano_settings()
    try:
        if s.provider == "google":
            if not s.google_maps_api_key:
                raise HTTPException(
                    status_code=503,
                    detail="STREETVIEW_PROVIDER=google requires GOOGLE_MAPS_API_KEY (or GOOGLE_STREETVIEW_API_KEY).",
                )
            return sample_panos_google(req, api_key=s.google_maps_api_key)
        return sample_panos_stub(req)
    except StreetViewInsufficientCoverageError as e:
        raise HTTPException(
            status_code=503,
            detail={"message": str(e), "debug": e.debug},
        ) from e
    except StreetViewMetadataError as e:
        raise HTTPException(
            status_code=502,
            detail={"message": str(e), "metadata_status": e.status},
        ) from e
