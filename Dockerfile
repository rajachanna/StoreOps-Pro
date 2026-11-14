FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . && \
    useradd --uid 10001 --create-home demo && mkdir -p /data && chown demo:demo /data
USER demo
ENV STOREOPS_DB=/data/storeops.sqlite
EXPOSE 8000
CMD ["uvicorn","storeops.api:app","--host","0.0.0.0","--port","8000"]
