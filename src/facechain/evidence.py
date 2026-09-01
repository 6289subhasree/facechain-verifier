from __future__ import annotations

import hashlib
import json

from facechain.models import MatchEvidence


def canonical_evidence_bytes(evidence: MatchEvidence) -> bytes:
    """Serialize evidence deterministically so anyone can reproduce its fingerprint."""

    payload = evidence.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def evidence_hash(evidence: MatchEvidence) -> str:
    """Return the SHA-256 evidence fingerprint with an explicit hex prefix."""

    return "0x" + hashlib.sha256(canonical_evidence_bytes(evidence)).hexdigest()

