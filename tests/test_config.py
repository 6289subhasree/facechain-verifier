import pytest
from pydantic import ValidationError

from facechain.config import Settings


def test_settings_default_to_local_evm() -> None:
    settings = Settings(_env_file=None)
    registry = settings.build_registry()
    assert registry.chain_name == "EthereumTester (local EVM)"


def test_partial_evm_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(evm_rpc_url="https://rpc.example", _env_file=None)
