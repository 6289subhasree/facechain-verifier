from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from typing import Annotated

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from facechain.config import Settings
from facechain.face import FaceProcessingError
from facechain.models import PipelineResult
from facechain.pipeline import FaceChainPipeline, NoWebMatchError
from facechain.search import GoogleVisionWebSearch, SearchProviderError

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PipelineFactory = Callable[[], FaceChainPipeline]


def _default_pipeline_factory(settings: Settings) -> PipelineFactory:
    def factory() -> FaceChainPipeline:
        if settings.google_vision_api_key is None:
            raise SearchProviderError(
                "Live discovery is not configured. Add GOOGLE_VISION_API_KEY to .env."
            )
        client = httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True)
        search = GoogleVisionWebSearch(
            settings.google_vision_api_key.get_secret_value(), client=client
        )
        return FaceChainPipeline.with_insightface(
            search_provider=search,
            registry=settings.build_registry(),
            threshold=settings.face_match_threshold,
            max_results=settings.max_search_results,
            http_client=client,
        )

    return factory


def create_app(
    *,
    settings: Settings | None = None,
    pipeline_factory: PipelineFactory | None = None,
) -> FastAPI:
    runtime = settings or Settings()
    factory = pipeline_factory or _default_pipeline_factory(runtime)
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
        return {
            "status": "ready" if runtime.google_vision_api_key else "configuration-required",
            "discovery": {
                "provider": "Google Vision Web Detection",
                "configured": bool(runtime.google_vision_api_key),
            },
            "face_model": "InsightFace buffalo_l (ArcFace)",
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

    return app


app = create_app()


def main() -> None:
    uvicorn.run("facechain.api:app", host="0.0.0.0", port=8000, reload=False)
