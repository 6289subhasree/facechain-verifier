import pytest
from pydantic import ValidationError

from facechain.config import Settings


def test_settings_default_to_local_evm() -> None:
    settings = Settings(_env_file=None)
    registry = settings.build_registry()
    assert registry.chain_name == "EthereumTester (local EVM)"
    assert settings.face_model_name == "buffalo_l"
    assert settings.face_detection_size == 640


def test_partial_evm_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(evm_rpc_url="https://rpc.example", _env_file=None)


def test_face_model_must_be_a_supported_insightface_pack() -> None:
    with pytest.raises(ValidationError):
        Settings(face_model_name="unknown", _env_file=None)


def test_face_detection_size_must_be_a_supported_multiple() -> None:
    with pytest.raises(ValidationError):
        Settings(face_detection_size=333, _env_file=None)
