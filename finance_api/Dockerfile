FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn==0.29.0 \
    duckdb==1.5.1 \
    pandas==2.2.2 \
    numpy==1.26.4 \
    pyyaml==6.0.1

COPY main.py quick.py quick.html ./

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
