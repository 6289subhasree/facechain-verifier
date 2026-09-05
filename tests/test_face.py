import sys
from types import ModuleType, SimpleNamespace

import pytest

from facechain.face import (
    FaceNotFoundError,
    InsightFaceEncoder,
    cosine_similarity,
    is_face_match,
)
from facechain.models import FaceScan


def scan(embedding: tuple[float, ...]) -> FaceScan:
    return FaceScan(
        embedding=embedding,
        bounding_box=(1, 2, 30, 40),
        detection_score=0.99,
        model="test-model",
    )


def test_cosine_similarity_and_match_threshold() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    matched, score = is_face_match(scan((1.0, 0.0)), scan((0.9, 0.1)), threshold=0.9)
    assert matched is True
    assert score > 0.99


def test_cosine_similarity_rejects_incompatible_embeddings() -> None:
    with pytest.raises(ValueError, match="equal dimensions"):
        cosine_similarity((1.0, 0.0), (1.0,))


def test_encoder_selects_largest_face(monkeypatch: pytest.MonkeyPatch) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_bytes = cv2.imencode(".png", np.zeros((20, 20, 3), dtype=np.uint8))[1].tobytes()
    small = SimpleNamespace(
        bbox=np.array([0, 0, 3, 3]),
        det_score=0.8,
        normed_embedding=np.array([1.0, 0.0]),
    )
    large = SimpleNamespace(
        bbox=np.array([1, 2, 10, 12]),
        det_score=0.95,
        normed_embedding=np.array([0.0, 1.0]),
    )
    fake_app = SimpleNamespace(get=lambda _image: [small, large])

    result = InsightFaceEncoder(app=fake_app).encode(image_bytes)

    assert result.bounding_box == (1, 2, 10, 12)
    assert result.embedding == (0.0, 1.0)


def test_encoder_reports_missing_face() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_bytes = cv2.imencode(".png", np.zeros((20, 20, 3), dtype=np.uint8))[1].tobytes()
    fake_app = SimpleNamespace(get=lambda _image: [])

    with pytest.raises(FaceNotFoundError, match="no face"):
        InsightFaceEncoder(app=fake_app).encode(image_bytes)


def test_encoder_loads_only_required_models(monkeypatch: pytest.MonkeyPatch) -> None:
    constructor_options: dict[str, object] = {}
    prepared_options: dict[str, object] = {}

    class FakeFaceAnalysis:
        def __init__(self, **kwargs: object) -> None:
            constructor_options.update(kwargs)

        def prepare(self, **kwargs: object) -> None:
            prepared_options.update(kwargs)

    insightface = ModuleType("insightface")
    insightface_app = ModuleType("insightface.app")
    insightface_app.FaceAnalysis = FakeFaceAnalysis  # type: ignore[attr-defined]
    insightface.app = insightface_app  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface", insightface)
    monkeypatch.setitem(sys.modules, "insightface.app", insightface_app)

    encoder = InsightFaceEncoder(model_name="buffalo_s", detection_size=(320, 320))
    encoder._load_app()

    assert constructor_options == {
        "name": "buffalo_s",
        "allowed_modules": ["detection", "recognition"],
        "providers": ["CPUExecutionProvider"],
    }
    assert prepared_options == {"ctx_id": -1, "det_size": (320, 320)}
