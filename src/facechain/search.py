from __future__ import annotations

import base64
import ipaddress
import socket
from collections.abc import Iterable
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from facechain.models import SearchCandidate

GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
MAX_IMAGE_BYTES = 12 * 1024 * 1024


class SearchProviderError(RuntimeError):
    """Raised when a reverse-image provider cannot return usable results."""


class ReverseImageSearch(Protocol):
    name: str

    def search(self, image_bytes: bytes, *, max_results: int = 10) -> list[SearchCandidate]: ...


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
