from __future__ import annotations

from dataclasses import dataclass

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from web3 import EthereumTesterProvider, HTTPProvider, Web3

from facechain.evidence import evidence_hash
from facechain.models import ChainReceipt, MatchEvidence, VerificationResult

PROTOCOL_PREFIX = b"FACECHAIN:v1:"


@dataclass
class EthereumEvidenceRegistry:
    """Anchor and verify evidence hashes using Ethereum transaction calldata.

    The default provider is a deterministic local EVM supplied by eth-tester. A
    transaction is mined into a real EVM block, and its immutable calldata stores
    the protocol marker plus the 32-byte evidence fingerprint.
    """

    web3: Web3
    chain_name: str = "EthereumTester (local EVM)"
    signing_account: LocalAccount | None = None
    explorer_base_url: str | None = None

    @classmethod
    def local(cls) -> EthereumEvidenceRegistry:
        return cls(web3=Web3(EthereumTesterProvider()))

    @classmethod
    def rpc(
        cls,
        rpc_url: str,
        private_key: str,
        *,
        chain_name: str,
        explorer_base_url: str | None = None,
    ) -> EthereumEvidenceRegistry:
        """Connect to a persistent EVM network using a dedicated signing key."""

        if not rpc_url.strip() or not private_key.strip():
            raise ValueError("both EVM_RPC_URL and EVM_PRIVATE_KEY are required")
        web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        if not web3.is_connected():
            raise RuntimeError(f"could not connect to configured EVM network: {chain_name}")
        return cls(
            web3=web3,
            chain_name=chain_name,
            signing_account=web3.eth.account.from_key(private_key),
            explorer_base_url=explorer_base_url.rstrip("/") if explorer_base_url else None,
        )

    @property
    def sender(self) -> ChecksumAddress:
        if self.signing_account is not None:
            return self.signing_account.address
        accounts = self.web3.eth.accounts
        if not accounts:
            raise RuntimeError("The configured EVM provider exposes no funded account")
        return accounts[0]

    def anchor(self, evidence: MatchEvidence) -> ChainReceipt:
        digest = evidence_hash(evidence)
        calldata = PROTOCOL_PREFIX + bytes.fromhex(digest.removeprefix("0x"))
        transaction = {
            "from": self.sender,
            "to": self.sender,
            "value": 0,
            "data": calldata,
        }
        if self.signing_account is None:
            tx_hash = self.web3.eth.send_transaction(transaction)
        else:
            transaction.update(
                {
                    "chainId": self.web3.eth.chain_id,
                    "nonce": self.web3.eth.get_transaction_count(self.sender, "pending"),
                    "gas": self.web3.eth.estimate_gas(transaction),
                    "gasPrice": self.web3.eth.gas_price,
                }
            )
            signed = self.signing_account.sign_transaction(transaction)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        mined = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if mined.status != 1:
            raise RuntimeError("Evidence anchor transaction reverted")
        return ChainReceipt(
            chain_name=self.chain_name,
            chain_id=self.web3.eth.chain_id,
            transaction_hash=tx_hash.hex(),
            block_number=mined.blockNumber,
            sender=self.sender,
            evidence_hash=digest,
            explorer_url=(
                f"{self.explorer_base_url}/{tx_hash.hex()}" if self.explorer_base_url else None
            ),
        )

    def verify(self, evidence: MatchEvidence, transaction_hash: str) -> VerificationResult:
        expected = evidence_hash(evidence)
        transaction = self.web3.eth.get_transaction(transaction_hash)
        calldata = bytes(transaction["input"])

        if not calldata.startswith(PROTOCOL_PREFIX):
            return VerificationResult(
                verified=False,
                expected_hash=expected,
                on_chain_hash="",
                transaction_hash=transaction_hash,
                reason="Transaction does not contain a FaceChain v1 record",
            )

        on_chain = "0x" + calldata[len(PROTOCOL_PREFIX) :].hex()
        matches = expected == on_chain
        return VerificationResult(
            verified=matches,
            expected_hash=expected,
            on_chain_hash=on_chain,
            transaction_hash=transaction_hash,
            reason="Evidence fingerprint matches the on-chain record"
            if matches
            else "Evidence has changed since it was anchored",
        )
