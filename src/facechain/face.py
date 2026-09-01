from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from facechain.models import FaceScan

DEFAULT_MODEL = "buffalo_l"


class FaceProcessingError(RuntimeError):
    """Base exception for image decoding and face-processing failures."""


class InvalidImageError(FaceProcessingError):
    """Raised when uploaded bytes are not a decodable image."""


class FaceNotFoundError(FaceProcessingError):
    """Raised when the detector cannot find a face in an image."""


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine similarity without requiring NumPy in the core package."""

    if len(left) != len(right) or not left:
        raise ValueError("embeddings must be non-empty and have equal dimensions")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embeddings must not be zero vectors")
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def is_face_match(query: FaceScan, candidate: FaceScan, threshold: float = 0.45) -> tuple[bool, float]:
    """Return a thresholded match decision and the underlying similarity score."""

    if not -1 <= threshold <= 1:
        raise ValueError("threshold must be between -1 and 1")
    score = cosine_similarity(query.embedding, candidate.embedding)
    return score >= threshold, score


class InsightFaceEncoder:
    """Detect and encode the most prominent face using InsightFace ArcFace.

    Heavy computer-vision dependencies are imported lazily so evidence-only
    verification remains lightweight. Install them with ``pip install -e .[face]``.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        detection_size: tuple[int, int] = (640, 640),
        app: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.detection_size = detection_size
        self._app = app

    def _load_app(self) -> Any:
        if self._app is not None:
            return self._app
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise FaceProcessingError(
                "InsightFace is not installed; run `pip install -e '.[face]'`"
            ) from exc
        self._app = FaceAnalysis(name=self.model_name, providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=self.detection_size)
        return self._app

    def encode(self, image_bytes: bytes) -> FaceScan:
        """Decode an image, find faces, and encode the largest detected face."""

        if not image_bytes:
            raise InvalidImageError("image is empty")
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise FaceProcessingError(
                "OpenCV and NumPy are required; run `pip install -e '.[face]'`"
            ) from exc

        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidImageError("uploaded bytes are not a supported image")

        faces = self._load_app().get(image)
        if not faces:
            raise FaceNotFoundError("no face was detected; use a clear, front-facing image")

        face = max(
            faces,
            key=lambda item: max(0.0, float(item.bbox[2] - item.bbox[0]))
            * max(0.0, float(item.bbox[3] - item.bbox[1])),
        )
        embedding = tuple(float(value) for value in face.normed_embedding)
        bounding_box = tuple(round(float(value)) for value in face.bbox)
        return FaceScan(
            embedding=embedding,
            bounding_box=bounding_box,
            detection_score=float(face.det_score),
            model=f"insightface/{self.model_name}",
        )
