# Research-only image. Build is a separate, network-enabled supply-chain step.
# Pin/review base digest and transitive wheel hashes for a production release.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir 'numpy==2.3.5' 'scipy==1.17.0' 'scikit-learn==1.8.0' && python -m pip install --no-cache-dir --no-deps .
USER 65532:65532
ENTRYPOINT ["python", "-m", "atlas_pro.sandbox_entry"]
CMD ["--demo"]
