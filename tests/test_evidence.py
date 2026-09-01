from datetime import UTC, datetime

from facechain.evidence import canonical_evidence_bytes, evidence_hash
from facechain.models import MatchEvidence


def sample_evidence(**updates: object) -> MatchEvidence:
    values = {
        "source_url": "https://example.org/post/42",
        "image_url": "https://example.org/media/face.jpg",
        "title": "Public post",
        "search_provider": "test-provider",
        "search_rank": 1,
        "face_model": "test-model",
        "similarity_score": 0.91,
        "matched": True,
        "discovered_at": datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    }
    values.update(updates)
    return MatchEvidence(**values)


def test_hash_is_deterministic() -> None:
    evidence = sample_evidence()
    assert evidence_hash(evidence) == evidence_hash(evidence)
    assert canonical_evidence_bytes(evidence).startswith(b'{"discovered_at"')


def test_material_change_changes_hash() -> None:
    original = sample_evidence()
    changed = sample_evidence(title="Altered public post")
    assert evidence_hash(original) != evidence_hash(changed)
