import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from facechain.search import (
    GoogleVisionWebSearch,
    SearchProviderError,
    SerpApiGoogleLensSearch,
    prepare_serpapi_image,
    require_public_url,
)


def jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), "#806040").save(output, format="JPEG")
    return output.getvalue()


def test_serpapi_upload_and_lens_results_are_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/image":
            assert request.method == "POST"
            assert b"test-key" in request.content
            return httpx.Response(200, json={"image_id": "uploaded-image-id"})
        assert request.url.params["engine"] == "google_lens"
        assert request.url.params["image_id"] == "uploaded-image-id"
        return httpx.Response(
            200,
            json={
                "visual_matches": [
                    {
                        "position": 1,
                        "title": "Matching Instagram post",
                        "link": "https://www.instagram.com/p/example/",
                        "image": "https://cdn.example/matching-face.jpg",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = SerpApiGoogleLensSearch("test-key", client=client).search(jpeg_bytes())

    assert len(results) == 1
    assert results[0].provider == "serpapi-google-lens"
    assert str(results[0].source_url) == "https://www.instagram.com/p/example/"


def test_serpapi_image_is_jpeg_below_upload_limit() -> None:
    encoded = prepare_serpapi_image(jpeg_bytes())
    assert encoded.startswith(b"\xff\xd8")
    assert len(encoded) <= 500_000


def test_google_vision_results_are_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-key"
        request_body = json.loads(request.content)
        assert request_body["requests"][0]["features"][0]["type"] == "WEB_DETECTION"
        return httpx.Response(
            200,
            json={
                "responses": [
                    {
                        "webDetection": {
                            "pagesWithMatchingImages": [
                                {
                                    "url": "https://social.example/post/7",
                                    "pageTitle": "A real public post",
                                    "fullMatchingImages": [
                                        {"url": "https://cdn.example/face.jpg"}
                                    ],
                                }
                            ]
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = GoogleVisionWebSearch("test-key", client=client).search(b"scan", max_results=3)

    assert len(results) == 1
    assert str(results[0].source_url) == "https://social.example/post/7"
    assert results[0].rank == 1


def test_google_vision_surfaces_provider_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"responses": [{"error": {"message": "API disabled"}}]}
            )
        )
    )
    with pytest.raises(SearchProviderError, match="API disabled"):
        GoogleVisionWebSearch("test-key", client=client).search(b"scan")


def test_private_candidate_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "facechain.search.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(SearchProviderError, match="non-public"):
        require_public_url("http://example.test/face.jpg")
