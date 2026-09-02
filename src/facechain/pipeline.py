from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from facechain.blockchain import EthereumEvidenceRegistry
from facechain.face import FaceProcessingError, InsightFaceEncoder, is_face_match
from facechain.models import (
    CandidateEvaluation,
    EvidenceBundle,
    FaceScan,
    MatchEvidence,
    PipelineResult,
)
from facechain.search import ReverseImageSearch, SearchProviderError, download_public_image


class NoWebMatchError(RuntimeError):
    """Raised when discovery finishes without a biometric match."""


class FaceEncoder(Protocol):
    def encode(self, image_bytes: bytes) -> FaceScan: ...


@dataclass
class FaceChainPipeline:
    """Orchestrate scan, live discovery, biometric verification, and EVM proof."""

    search_provider: ReverseImageSearch
    registry: EthereumEvidenceRegistry
    encoder: FaceEncoder
    threshold: float = 0.45
    max_results: int = 10
    http_client: httpx.Client | None = None

    @classmethod
    def with_insightface(
        cls,
        search_provider: ReverseImageSearch,
        registry: EthereumEvidenceRegistry | None = None,
        **kwargs: object,
    ) -> FaceChainPipeline:
        return cls(
            search_provider=search_provider,
            registry=registry or EthereumEvidenceRegistry.local(),
            encoder=InsightFaceEncoder(),
            **kwargs,
        )

    def run(self, image_bytes: bytes) -> PipelineResult:
        query_face = self.encoder.encode(image_bytes)
        candidates = self.search_provider.search(image_bytes, max_results=self.max_results)
        evaluations: list[CandidateEvaluation] = []

        for candidate in candidates:
            try:
                candidate_bytes = download_public_image(
                    str(candidate.image_url), client=self.http_client
                )
                candidate_face = self.encoder.encode(candidate_bytes)
                matched, score = is_face_match(query_face, candidate_face, self.threshold)
                evaluations.append(
                    CandidateEvaluation(
                        candidate=candidate,
                        similarity_score=score,
                        matched=matched,
                    )
                )
            except (FaceProcessingError, SearchProviderError, ValueError) as exc:
                evaluations.append(CandidateEvaluation(candidate=candidate, error=str(exc)))

        matches = [item for item in evaluations if item.matched]
        if not matches:
            raise NoWebMatchError(
                f"no face exceeded the {self.threshold:.2f} similarity threshold "
                f"across {len(evaluations)} candidate(s)"
            )
        best = max(matches, key=lambda item: item.similarity_score or -1.0)
        assert best.similarity_score is not None

        evidence = MatchEvidence(
            source_url=best.candidate.source_url,
            image_url=best.candidate.image_url,
            title=best.candidate.title,
            search_provider=best.candidate.provider,
            search_rank=best.candidate.rank,
            face_model=query_face.model,
            similarity_score=best.similarity_score,
            matched=True,
            metadata={
                "threshold": self.threshold,
                "query_bounding_box": query_face.bounding_box,
                "candidates_evaluated": len(evaluations),
            },
        )
        receipt = self.registry.anchor(evidence)
        verification = self.registry.verify(evidence, receipt.transaction_hash)
        if not verification.verified:
            raise RuntimeError("newly anchored evidence failed immediate verification")
        return PipelineResult(
            query_face=query_face,
            evaluations=tuple(evaluations),
            evidence=evidence,
            receipt=receipt,
            verification=verification,
            proof_bundle=EvidenceBundle(evidence=evidence, receipt=receipt),
        )
