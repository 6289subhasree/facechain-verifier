from __future__ import annotations

from dataclasses import dataclass

from eth_typing import ChecksumAddress
from web3 import EthereumTesterProvider, Web3

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

    @classmethod
    def local(cls) -> EthereumEvidenceRegistry:
        return cls(web3=Web3(EthereumTesterProvider()))

    @property
    def sender(self) -> ChecksumAddress:
        accounts = self.web3.eth.accounts
        if not accounts:
            raise RuntimeError("The configured EVM provider exposes no funded account")
        return accounts[0]

    def anchor(self, evidence: MatchEvidence) -> ChainReceipt:
        digest = evidence_hash(evidence)
        calldata = PROTOCOL_PREFIX + bytes.fromhex(digest.removeprefix("0x"))
        tx_hash = self.web3.eth.send_transaction(
            {
                "from": self.sender,
                "to": self.sender,
                "value": 0,
                "data": calldata,
            }
        )
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
