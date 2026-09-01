from datetime import datetime, timezone

from facechain.blockchain import EthereumEvidenceRegistry
from facechain.models import MatchEvidence


def evidence(title: str = "Original post") -> MatchEvidence:
    return MatchEvidence(
        source_url="https://example.org/post/42",
        image_url="https://example.org/media/face.jpg",
        title=title,
        search_provider="test-provider",
        search_rank=1,
        face_model="test-model",
        similarity_score=0.91,
        matched=True,
        discovered_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )


def test_round_trip_verification() -> None:
    registry = EthereumEvidenceRegistry.local()
    original = evidence()
    receipt = registry.anchor(original)

    result = registry.verify(original, receipt.transaction_hash)

    assert result.verified is True
    assert result.expected_hash == receipt.evidence_hash
    assert result.on_chain_hash == receipt.evidence_hash


def test_tampering_is_detected() -> None:
    registry = EthereumEvidenceRegistry.local()
    receipt = registry.anchor(evidence())

    result = registry.verify(evidence(title="Tampered post"), receipt.transaction_hash)

    assert result.verified is False
    assert result.reason == "Evidence has changed since it was anchored"

