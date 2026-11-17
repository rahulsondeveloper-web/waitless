"""Geocoding behind one interface (decision D25): OpenStreetMap Nominatim now, Google when a key is set.

Used only server-side when staff look up an address (never from guests' browsers), cached for 30 days and
rate limited, as Nominatim's usage policy asks. `MAPS_PROVIDER=google` + `GOOGLE_MAPS_API_KEY` switches.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis import get_redis

log = logging.getLogger(__name__)
CACHE_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True)
class Place:
    lat: float
    lng: float
    label: str
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class Geocoder(Protocol):
    name: str

    async def search(self, query: str, *, country: str = "in", limit: int = 5) -> list[Place]: ...


class NominatimGeocoder:
    name = "nominatim"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self.base = s.nominatim_url.rstrip("/")
        self.headers = {"User-Agent": s.geocode_user_agent, "Accept-Language": "en"}
        self.transport = transport

    async def search(self, query: str, *, country: str = "in", limit: int = 5) -> list[Place]:
        params = {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": limit, "countrycodes": country}
        async with httpx.AsyncClient(timeout=8, headers=self.headers, transport=self.transport) as c:
            r = await c.get(f"{self.base}/search", params=params)
        r.raise_for_status()
        out = []
        for row in r.json():
            a = row.get("address") or {}
            out.append(
                Place(
                    lat=float(row["lat"]),
                    lng=float(row["lon"]),
                    label=row.get("display_name", ""),
                    city=a.get("city") or a.get("town") or a.get("village") or a.get("suburb"),
                    state=a.get("state"),
                    postal_code=a.get("postcode"),
                )
            )
        return out


class GoogleGeocoder:
    name = "google"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.key = get_settings().google_maps_api_key
        if not self.key:
            raise AppError("Google Maps is not configured.", code="MAPS_NOT_CONFIGURED", status_code=503)
        self.transport = transport

    async def search(self, query: str, *, country: str = "in", limit: int = 5) -> list[Place]:
        params = {"address": query, "key": self.key, "region": country, "components": f"country:{country.upper()}"}
        async with httpx.AsyncClient(timeout=8, transport=self.transport) as c:
            r = await c.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            log.warning("google geocoding: %s", data.get("status"))
            raise AppError("Address lookup is unavailable right now.", code="GEOCODER_ERROR", status_code=503)
        out = []
        for row in data.get("results", [])[:limit]:
            comp = {t: c["long_name"] for c in row.get("address_components", []) for t in c.get("types", [])}
            loc = row["geometry"]["location"]
            out.append(
                Place(
                    lat=float(loc["lat"]),
                    lng=float(loc["lng"]),
                    label=row.get("formatted_address", ""),
                    city=comp.get("locality") or comp.get("administrative_area_level_2"),
                    state=comp.get("administrative_area_level_1"),
                    postal_code=comp.get("postal_code"),
                )
            )
        return out


def get_geocoder() -> Geocoder:
    return GoogleGeocoder() if get_settings().maps_provider == "google" else NominatimGeocoder()


async def geocode(query: str, geocoder: Geocoder | None = None) -> list[Place]:
    """Cached lookup. Errors become a friendly 503 — the owner can still drop the pin by hand."""
    q = " ".join(query.split())[:200]
    if len(q) < 3:
        return []
    g = geocoder or get_geocoder()
    key = f"geo:{g.name}:{hashlib.sha256(q.lower().encode()).hexdigest()[:32]}"
    redis = get_redis()
    if redis is not None:
        hit = await redis.get(key)
        if hit:
            return [Place(**p) for p in json.loads(hit)]
    try:
        places = await g.search(q)
    except AppError:
        raise
    except Exception as exc:  # network, 4xx/5xx
        log.warning("geocoding failed (%s): %s", g.name, exc)
        raise AppError(
            "Address lookup is unavailable right now — drop the pin on the map instead.",
            code="GEOCODER_ERROR",
            status_code=503,
        ) from exc
    if redis is not None:
        await redis.set(key, json.dumps([asdict(p) for p in places]), ex=CACHE_SECONDS)
    return places
