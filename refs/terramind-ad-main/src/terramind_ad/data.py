from geojson_pydantic import FeatureCollection
from pydantic import BaseModel


class DisasterSite(BaseModel):
    """Configuration for a disaster site."""

    id: str
    name: str
    event_type: str
    event_date: str
    observed_event: FeatureCollection
    epsg: int
    historical_start: str
    historical_end: str
    description: str = ""
    default_patch_x: int | None = None
    default_patch_y: int | None = None


class SitesConfig(BaseModel):
    """Root configuration with all sites."""

    sites: list[DisasterSite]
