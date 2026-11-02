# 1000Jobs ATS Lab v1.4 - the app (User page /user, Admin page /admin) in one container.
#   docker build -t atslab .
#   docker run -d -p 8501:8501 -v atslab-data:/data -v /path/to/secrets.toml:/app/.streamlit/secrets.toml:ro atslab
# See DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ATSLAB_DATA_DIR=/data HF_HOME=/opt/hf HF_HUB_DISABLE_TELEMETRY=1

# Chromium prints the PDF reports; the fonts are a fallback when Google Fonts cannot be reached
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# the meaning-match model, downloaded once into the image (the same pinned version as ATSLab_v3.py)
RUN python -c "from sentence_transformers import SentenceTransformer as S; \
S('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41', device='cpu')"

COPY . .
RUN useradd --create-home lab && mkdir -p /data && chown -R lab /data /app /opt/hf
USER lab

EXPOSE 8501
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["python", "run_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
