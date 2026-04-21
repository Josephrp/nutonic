"""Resolve STAC item datetime for Dynamic World alignment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def fetch_item_datetime_iso(
    *,
    stac_url: str,
    collection: str,
    item_id: str,
) -> str | None:
    from pystac_client import Client

    client = Client.open(stac_url)
    for item in client.search(collections=[collection], ids=[item_id], max_items=1).items():
        if item.datetime is None:
            return None
        dt = item.datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def ee_filter_dates_from_iso(iso: str) -> tuple[str, str]:
    """Return ``(start, end)`` strings for ``ee.ImageCollection.filterDate`` (end exclusive day)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    start = dt.date().isoformat()
    end = (dt.date() + timedelta(days=1)).isoformat()
    return start, end


def ee_filter_dates_from_query(datetime_query: str) -> tuple[str, str]:
    """Fallback when item datetime missing: use full STAC query window (EE ``filterDate``)."""
    parts = datetime_query.strip().split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip()[:10], parts[1].strip()[:10]
    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=90)
    return start.isoformat(), end.isoformat()
