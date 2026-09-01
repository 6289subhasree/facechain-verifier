from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from facechain.blockchain import EthereumEvidenceRegistry
from facechain.models import MatchEvidence

app = typer.Typer(no_args_is_help=True, help="FaceChain evidence anchoring utilities.")
console = Console()


def _load_evidence(path: Path) -> MatchEvidence:
    return MatchEvidence.model_validate_json(path.read_text(encoding="utf-8"))


@app.command()
def proof_demo(evidence_file: Path) -> None:
    """Anchor an evidence JSON file and immediately reverify it on a local EVM."""

    evidence = _load_evidence(evidence_file)
    registry = EthereumEvidenceRegistry.local()
    receipt = registry.anchor(evidence)
    result = registry.verify(evidence, receipt.transaction_hash)

    console.print(Panel.fit("BLOCKCHAIN VERIFICATION PASSED", style="bold green"))
    console.print_json(json.dumps(receipt.model_dump(mode="json")))
    console.print_json(json.dumps(result.model_dump(mode="json")))
    if not result.verified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

