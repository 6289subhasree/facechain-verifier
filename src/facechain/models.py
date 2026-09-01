from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SearchCandidate(BaseModel):
    """A public result returned by a live reverse-image search provider."""

    model_config = ConfigDict(frozen=True)

    source_url: HttpUrl
    image_url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    provider: str = Field(min_length=1, max_length=100)
    rank: int = Field(ge=1)


class MatchEvidence(BaseModel):
    """Canonical evidence committed to the blockchain."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    source_url: HttpUrl
    image_url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    search_provider: str = Field(min_length=1, max_length=100)
    search_rank: int = Field(ge=1)
    face_model: str = Field(min_length=1, max_length=100)
    similarity_score: float = Field(ge=-1, le=1)
    matched: bool
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("discovered_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("discovered_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class ChainReceipt(BaseModel):
    """Proof that an evidence fingerprint was anchored on an EVM chain."""

    model_config = ConfigDict(frozen=True)

    chain_name: str
    chain_id: int
    transaction_hash: str
    block_number: int
    sender: str
    evidence_hash: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verified: bool
    expected_hash: str
    on_chain_hash: str
    transaction_hash: str
    reason: str

