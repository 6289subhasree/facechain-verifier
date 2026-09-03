from __future__ import annotations

import os
from collections.abc import Callable
from importlib.resources import files
from typing import Annotated

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from web3.exceptions import TransactionNotFound

from facechain.blockchain import EthereumEvidenceRegistry
from facechain.config import Settings
from facechain.face import FaceProcessingError
from facechain.models import EvidenceBundle, PipelineResult, VerificationResult
from facechain.pipeline import FaceChainPipeline, NoWebMatchError
from facechain.search import GoogleVisionWebSearch, SearchProviderError, SerpApiGoogleLensSearch

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PipelineFactory = Callable[[], FaceChainPipeline]


def _default_pipeline_factory(
    settings: Settings, registry: EthereumEvidenceRegistry
) -> PipelineFactory:
    def factory() -> FaceChainPipeline:
        if settings.serpapi_api_key is None and settings.google_vision_api_key is None:
            raise SearchProviderError(
                "Live discovery is not configured. Add SERPAPI_API_KEY to .env."
            )
        client = httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True)
        if settings.serpapi_api_key is not None:
            search = SerpApiGoogleLensSearch(
                settings.serpapi_api_key.get_secret_value(),
                client=client,
                country=settings.search_country,
                language=settings.search_language,
            )
        else:
            assert settings.google_vision_api_key is not None
            search = GoogleVisionWebSearch(
                settings.google_vision_api_key.get_secret_value(), client=client
            )
        return FaceChainPipeline.with_insightface(
            search_provider=search,
            registry=registry,
            model_name=settings.face_model_name,
            threshold=settings.face_match_threshold,
            max_results=settings.max_search_results,
            http_client=client,
        )

    return factory


def create_app(
    *,
    settings: Settings | None = None,
    pipeline_factory: PipelineFactory | None = None,
    registry: EthereumEvidenceRegistry | None = None,
) -> FastAPI:
    runtime = settings or Settings()
    proof_registry = registry or runtime.build_registry()
    factory = pipeline_factory or _default_pipeline_factory(runtime, proof_registry)
    web_root = files("facechain").joinpath("web")

    app = FastAPI(
        title="FaceChain Verifier",
        version="0.1.0",
        description="Face scan to public-web match to reproducible EVM evidence proof.",
    )
    app.mount("/static", StaticFiles(directory=str(web_root)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(web_root.joinpath("index.html")))

    @app.get("/api/health")
    def health() -> dict[str, object]:
        public_chain = bool(runtime.evm_rpc_url and runtime.evm_private_key)
        configured = bool(runtime.serpapi_api_key or runtime.google_vision_api_key)
        provider = "Not configured"
        if runtime.serpapi_api_key:
            provider = "SerpAPI Google Lens"
        elif runtime.google_vision_api_key:
            provider = "Google Vision Web Detection"
        return {
            "status": "ready" if configured else "configuration-required",
            "discovery": {
                "provider": provider,
                "configured": configured,
            },
            "face_model": f"InsightFace {runtime.face_model_name} (ArcFace)",
            "chain": {
                "mode": "public" if public_chain else "local",
                "name": runtime.evm_chain_name if public_chain else "EthereumTester (local EVM)",
            },
        }

    @app.post("/api/verify", response_model=PipelineResult)
    async def verify(
        image: Annotated[UploadFile, File(description="A clear face scan")],
        consent: Annotated[bool, Form()] = False,
    ) -> PipelineResult:
        if not consent:
            raise HTTPException(
                status_code=400,
                detail="Explicit consent is required before biometric processing.",
            )
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image.")

        image_bytes = await image.read(MAX_UPLOAD_BYTES + 1)
        await image.close()
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image must be 12 MB or smaller.")
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image is empty.")

        try:
            pipeline = factory()
            return await run_in_threadpool(pipeline.run, image_bytes)
        except NoWebMatchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FaceProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SearchProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/proofs/verify", response_model=VerificationResult)
    async def verify_existing_proof(bundle: EvidenceBundle) -> VerificationResult:
        if bundle.receipt.chain_id != proof_registry.web3.eth.chain_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Proof targets chain ID {bundle.receipt.chain_id}, but this server is "
                    f"connected to chain ID {proof_registry.web3.eth.chain_id}."
                ),
            )
        try:
            return await run_in_threadpool(
                proof_registry.verify,
                bundle.evidence,
                bundle.receipt.transaction_hash,
            )
        except TransactionNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Transaction was not found on the configured chain.",
            ) from exc

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "facechain.api:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
