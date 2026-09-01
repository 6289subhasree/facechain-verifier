from datetime import UTC, datetime

from fastapi.testclient import TestClient

from facechain.api import create_app
from facechain.config import Settings
from facechain.models import (
    CandidateEvaluation,
    ChainReceipt,
    FaceScan,
    MatchEvidence,
    PipelineResult,
    SearchCandidate,
    VerificationResult,
)


def completed_result() -> PipelineResult:
    candidate = SearchCandidate(
        source_url="https://social.example/post/7",
        image_url="https://cdn.example/face.jpg",
        title="Public match",
        provider="test-search",
        rank=1,
    )
    evidence = MatchEvidence(
        source_url=candidate.source_url,
        image_url=candidate.image_url,
        title=candidate.title,
        search_provider=candidate.provider,
        search_rank=1,
        face_model="test-arcface",
        similarity_score=0.97,
        matched=True,
        discovered_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    receipt = ChainReceipt(
        chain_name="test-chain",
        chain_id=1,
        transaction_hash="0xtransaction",
        block_number=42,
        sender="0xsender",
        evidence_hash="0xevidence",
    )
    verification = VerificationResult(
        verified=True,
        expected_hash="0xevidence",
        on_chain_hash="0xevidence",
        transaction_hash="0xtransaction",
        reason="Evidence fingerprint matches the on-chain record",
    )
    return PipelineResult(
        query_face=FaceScan(
            embedding=(1.0, 0.0),
            bounding_box=(0, 0, 100, 100),
            detection_score=0.99,
            model="test-arcface",
        ),
        evaluations=(CandidateEvaluation(candidate=candidate, similarity_score=0.97, matched=True),),
        evidence=evidence,
        receipt=receipt,
        verification=verification,
    )


class FakePipeline:
    def run(self, _image_bytes: bytes) -> PipelineResult:
        return completed_result()


def client() -> TestClient:
    app = create_app(
        settings=Settings(_env_file=None),
        pipeline_factory=lambda: FakePipeline(),
    )
    return TestClient(app)


def test_index_and_health_are_available() -> None:
    test_client = client()
    assert test_client.get("/").status_code == 200
    health = test_client.get("/api/health").json()
    assert health["chain"]["mode"] == "local"


def test_verification_requires_consent() -> None:
    response = client().post(
        "/api/verify",
        files={"image": ("face.jpg", b"image", "image/jpeg")},
        data={"consent": "false"},
    )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_verification_response_excludes_biometric_embedding() -> None:
    response = client().post(
        "/api/verify",
        files={"image": ("face.jpg", b"image", "image/jpeg")},
        data={"consent": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["verified"] is True
    assert "embedding" not in body["query_face"]
