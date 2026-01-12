FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PIP_NO_CACHE_DIR=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    wget \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install API deps
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -U pip \
  && pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cu121 \
    --extra-index-url https://pypi.org/simple \
    torch==2.3.1 \
  && pip install -r requirements.txt

# Install RF3 stack (per upstream docs: modelforge with [rf3] extras)
# Note: This can be heavy and may take time to build.
RUN git clone --depth 1 https://github.com/RosettaCommons/modelforge.git /opt/modelforge \
  && pip install -e "/opt/modelforge[rf3]"

# App code
COPY src ./src
ENV PYTHONPATH=/app/src

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

# The container app should mount a volume at /models for checkpoint caching.
ENV RF3_CKPT_PATH=/models/rf3.ckpt \
    RF3_WORKDIR=/tmp/rf3-demo

ENTRYPOINT ["/entrypoint.sh"]
