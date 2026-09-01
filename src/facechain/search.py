from __future__ import annotations

import base64
import io
import ipaddress
import socket
from collections.abc import Iterable
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from facechain.models import SearchCandidate

GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SERPAPI_IMAGE_ENDPOINT = "https://serpapi.com/image"
SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_UPLOAD_LIMIT = 500_000


class SearchProviderError(RuntimeError):
    """Raised when a reverse-image provider cannot return usable results."""


class ReverseImageSearch(Protocol):
    name: str

    def search(self, image_bytes: bytes, *, max_results: int = 10) -> list[SearchCandidate]: ...


def prepare_serpapi_image(image_bytes: bytes) -> bytes:
    """Normalize and compress a scan below SerpAPI's 500 KB upload limit."""

    if not image_bytes:
        raise SearchProviderError("cannot upload an empty image")
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            for quality in (88, 78, 68, 58, 48, 38):
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                encoded = output.getvalue()
                if len(encoded) <= SERPAPI_UPLOAD_LIMIT:
                    return encoded
    except (OSError, UnidentifiedImageError) as exc:
        raise SearchProviderError("scan could not be prepared for Google Lens") from exc
    raise SearchProviderError("scan could not be compressed below SerpAPI's 500 KB limit")


class SerpApiGoogleLensSearch:
    """Upload a scan and return live Google Lens visual matches through SerpAPI."""

    name = "serpapi-google-lens"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        country: str = "in",
        language: str = "en",
        image_endpoint: str = SERPAPI_IMAGE_ENDPOINT,
        search_endpoint: str = SERPAPI_SEARCH_ENDPOINT,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SERPAPI_API_KEY is required for Google Lens discovery")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.country = country
        self.language = language
        self.image_endpoint = image_endpoint
        self.search_endpoint = search_endpoint

    def _upload(self, image_bytes: bytes) -> str:
        upload_bytes = prepare_serpapi_image(image_bytes)
        try:
            response = self.client.post(
                self.image_endpoint,
                data={"api_key": self.api_key},
                files={"image": ("facechain-scan.jpg", upload_bytes, "image/jpeg")},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError(f"SerpAPI image upload failed: {exc}") from exc
        if body.get("error"):
            raise SearchProviderError(f"SerpAPI image upload failed: {body['error']}")
        image_id = body.get("image_id")
        if not image_id:
            raise SearchProviderError("SerpAPI image upload returned no image_id")
        return str(image_id)

    def search(self, image_bytes: bytes, *, max_results: int = 10) -> list[SearchCandidate]:
        if not 1 <= max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        image_id = self._upload(image_bytes)
        try:
            response = self.client.get(
                self.search_endpoint,
                params={
                    "engine": "google_lens",
                    "image_id": image_id,
                    "api_key": self.api_key,
                    "country": self.country,
                    "hl": self.language,
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError(f"Google Lens search failed: {exc}") from exc
        if body.get("error"):
            raise SearchProviderError(f"Google Lens search failed: {body['error']}")

        candidates: list[SearchCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in body.get("visual_matches") or []:
            source_url = item.get("link")
            image_url = item.get("image") or item.get("thumbnail")
            if not source_url or not image_url:
                continue
            key = (str(source_url), str(image_url))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                SearchCandidate(
                    source_url=source_url,
                    image_url=image_url,
                    title=item.get("title") or item.get("source") or "Google Lens visual match",
                    provider=self.name,
                    rank=int(item.get("position") or len(candidates) + 1),
                )
            )
            if len(candidates) >= max_results:
                break
        return candidates


def _image_from_page(page: dict[str, Any]) -> str | None:
    for key in ("fullMatchingImages", "partialMatchingImages"):
        images = page.get(key) or []
        if images and images[0].get("url"):
            return str(images[0]["url"])
    return None


class GoogleVisionWebSearch:
    """Find public pages containing the scan via Google Vision Web Detection."""

    name = "google-vision-web-detection"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        endpoint: str = GOOGLE_VISION_ENDPOINT,
    ) -> None:
        if not api_key.strip():
            raise ValueError("GOOGLE_VISION_API_KEY is required for live discovery")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20, follow_redirects=True)
        self.endpoint = endpoint

    def search(self, image_bytes: bytes, *, max_results: int = 10) -> list[SearchCandidate]:
        if not image_bytes:
            raise SearchProviderError("cannot search with an empty image")
        if not 1 <= max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")

        payload = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": max_results}],
                }
            ]
        }
        try:
            response = self.client.post(
                self.endpoint,
                params={"key": self.api_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError(f"Google Vision request failed: {exc}") from exc

        result = (body.get("responses") or [{}])[0]
        if result.get("error"):
            message = result["error"].get("message", "unknown provider error")
            raise SearchProviderError(f"Google Vision rejected the scan: {message}")

        pages = result.get("webDetection", {}).get("pagesWithMatchingImages", [])
        candidates: list[SearchCandidate] = []
        seen: set[tuple[str, str]] = set()
        for page in pages:
            source_url = page.get("url")
            image_url = _image_from_page(page)
            if not source_url or not image_url:
                continue
            key = (str(source_url), str(image_url))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                SearchCandidate(
                    source_url=source_url,
                    image_url=image_url,
                    title=page.get("pageTitle") or urlparse(str(source_url)).netloc,
                    provider=self.name,
                    rank=len(candidates) + 1,
                )
            )
            if len(candidates) >= max_results:
                break
        return candidates


def _resolved_addresses(hostname: str) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        records = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SearchProviderError(f"candidate image host could not be resolved: {hostname}") from exc
    for record in records:
        yield ipaddress.ip_address(record[4][0])


def require_public_url(url: str) -> None:
    """Reject local/private candidate URLs before server-side image downloads."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SearchProviderError("candidate image URL must be public HTTP(S)")
    if parsed.username or parsed.password:
        raise SearchProviderError("candidate image URL must not contain credentials")
    for address in _resolved_addresses(parsed.hostname):
        if not address.is_global:
            raise SearchProviderError("candidate image URL resolves to a non-public address")


def download_public_image(
    url: str,
    *,
    client: httpx.Client | None = None,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> bytes:
    """Download a bounded public image for biometric re-verification."""

    require_public_url(url)
    requester = client or httpx.Client(timeout=15, follow_redirects=True)
    try:
        with requester.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith("image/"):
                raise SearchProviderError("candidate URL did not return an image")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise SearchProviderError("candidate image exceeds the download limit")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise SearchProviderError(f"candidate image download failed: {exc}") from exc
    return b"".join(chunks)
