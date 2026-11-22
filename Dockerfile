# 1000Jobs ATS Lab v1.4 - the app (User page /user, Admin page /admin) in one container.
#   docker build -t atslab .
#   docker run -d -p 8501:8501 -v atslab-data:/data -v /path/to/secrets.toml:/app/.streamlit/secrets.toml:ro atslab
# See DEPLOY.md.
# Node 22 is copied in for "ATS Checker 3" (the open-source VeriWorkly ats-engine, MIT licence). It runs as a
# local command on the server; no resume leaves the machine. Without it the app still works: the card says
# "Not installed on this server" and the ATS Lab report is unchanged.
FROM node:22-slim AS node

FROM python:3.12-slim

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ATSLAB_DATA_DIR=/data HF_HOME=/opt/hf HF_HUB_DISABLE_TELEMETRY=1 TZ=Asia/Dubai

# Chromium prints the PDF reports; the fonts are a fallback when Google Fonts cannot be reached; tzdata makes the
# times in the History the team's local time (the app saves the server's local time)
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# the meaning-match model, downloaded once into the image (the same pinned version as ATSLab_v3.py)
RUN python -c "from sentence_transformers import SentenceTransformer as S; \
S('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41', device='cpu')"

# the open-source checker (MIT licence): installed once here, so it needs no network at run time
RUN npm install -g --no-audit --no-fund @veriworkly/ats-engine

COPY . .
RUN useradd --create-home lab && mkdir -p /data && chown -R lab /data /app /opt/hf
USER lab

EXPOSE 8501
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["python", "run_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
