from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from facechain.blockchain import EthereumEvidenceRegistry


class Settings(BaseSettings):
    """Runtime settings sourced from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    serpapi_api_key: SecretStr | None = None
    google_vision_api_key: SecretStr | None = None
    face_match_threshold: float = Field(default=0.45, ge=-1, le=1)
    max_search_results: int = Field(default=10, ge=1, le=50)
    http_timeout_seconds: float = Field(default=15, gt=0, le=60)
    search_country: str = Field(default="in", min_length=2, max_length=2)
    search_language: str = Field(default="en", min_length=2, max_length=5)

    evm_rpc_url: str | None = None
    evm_private_key: SecretStr | None = None
    evm_chain_name: str = "Sepolia"
    evm_explorer_url: str | None = "https://sepolia.etherscan.io/tx"

    @model_validator(mode="after")
    def require_complete_evm_credentials(self) -> Settings:
        if bool(self.evm_rpc_url) != bool(self.evm_private_key):
            raise ValueError("EVM_RPC_URL and EVM_PRIVATE_KEY must be configured together")
        return self

    def build_registry(self) -> EthereumEvidenceRegistry:
        if self.evm_rpc_url and self.evm_private_key:
            return EthereumEvidenceRegistry.rpc(
                self.evm_rpc_url,
                self.evm_private_key.get_secret_value(),
                chain_name=self.evm_chain_name,
                explorer_base_url=self.evm_explorer_url,
            )
        return EthereumEvidenceRegistry.local()
