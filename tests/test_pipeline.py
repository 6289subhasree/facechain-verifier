import httpx

from facechain.blockchain import EthereumEvidenceRegistry
from facechain.models import FaceScan, SearchCandidate
from facechain.pipeline import FaceChainPipeline


class FakeEncoder:
    def encode(self, image_bytes: bytes) -> FaceScan:
        embedding = (1.0, 0.0) if image_bytes in {b"query", b"matching-image"} else (0.0, 1.0)
        return FaceScan(
            embedding=embedding,
            bounding_box=(0, 0, 100, 100),
            detection_score=0.99,
            model="fake-arcface",
        )


class FakeSearch:
    name = "fake-live-search"

    def search(self, _image_bytes: bytes, *, max_results: int = 10) -> list[SearchCandidate]:
        return [
            SearchCandidate(
                source_url="https://social.example/post/not-it",
                image_url="https://cdn.example/not-it.jpg",
                title="Different person",
                provider=self.name,
                rank=1,
            ),
            SearchCandidate(
                source_url="https://social.example/post/match",
                image_url="https://cdn.example/match.jpg",
                title="Matching public post",
                provider=self.name,
                rank=2,
            ),
        ][:max_results]


def test_pipeline_runs_end_to_end(monkeypatch) -> None:
    monkeypatch.setattr("facechain.search.require_public_url", lambda _url: None)

    def handler(request: httpx.Request) -> httpx.Response:
        content = b"matching-image" if request.url.path.endswith("match.jpg") else b"other-image"
        return httpx.Response(200, content=content, headers={"content-type": "image/jpeg"})

    pipeline = FaceChainPipeline(
        search_provider=FakeSearch(),
        registry=EthereumEvidenceRegistry.local(),
        encoder=FakeEncoder(),
        threshold=0.8,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = pipeline.run(b"query")

    assert str(result.evidence.source_url).endswith("/post/match")
    assert result.evidence.similarity_score == 1.0
    assert result.receipt.evidence_hash == result.verification.on_chain_hash
    assert result.verification.verified is True
