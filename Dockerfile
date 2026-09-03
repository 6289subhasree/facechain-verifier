FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FACE_MODEL_NAME=buffalo_s

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir ".[face]" \
    && python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])"

EXPOSE 8000

CMD ["facechain-web"]
