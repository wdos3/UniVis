FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY ocr_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

ENV PYTHONPATH=/app \
    PADDLE_PDX_MODEL_SOURCE=BOS \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    PADDLEOCR_CPU_THREADS=8 \
    PADDLEOCR_ENABLE_MKLDNN=false

EXPOSE 8000

CMD ["uvicorn", "app.ocr_service:app", "--host", "0.0.0.0", "--port", "8000"]
