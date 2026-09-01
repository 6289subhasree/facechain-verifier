from datetime import UTC, datetime

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
        discovered_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
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


def test_signed_transaction_path_anchors_evidence() -> None:
    registry = EthereumEvidenceRegistry.local()
    backend = registry.web3.provider.ethereum_tester.backend
    signing_account = registry.web3.eth.account.from_key(backend.account_keys[0])
    signed_registry = EthereumEvidenceRegistry(
        web3=registry.web3,
        chain_name="EthereumTester (signed)",
        signing_account=signing_account,
        explorer_base_url="https://explorer.example/tx",
    )

    receipt = signed_registry.anchor(evidence())
    result = signed_registry.verify(evidence(), receipt.transaction_hash)

    assert result.verified is True
    assert str(receipt.explorer_url).endswith(receipt.transaction_hash)
