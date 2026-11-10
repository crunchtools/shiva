# Shiva -- mass SSH client
# Built on the Hummingbird Python builder image: ssh is needed at runtime, so
# the image keeps dnf to install openssh-clients.
#
# Run rootless (agent forwarded from the host, groups mounted read-only):
# (label=disable rather than :Z, so the agent socket and ~/.ssh keep their labels)
#   podman run --rm --security-opt label=disable \
#     -v "$SSH_AUTH_SOCK:/ssh-agent" -e SSH_AUTH_SOCK=/ssh-agent \
#     -v ~/.ssh/known_hosts:/root/.ssh/known_hosts:ro \
#     -v /usr/local/etc/shiva:/usr/local/etc/shiva:ro \
#     quay.io/crunchtools/shiva -g web uptime

# Stage 1: Lock (turn uv.lock into the exact dependency set to install)
FROM quay.io/hummingbird/python:3.14-fips-builder AS lock
USER 0
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /lock
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project \
      --format requirements-txt -o /requirements.txt

FROM quay.io/hummingbird/python:3.14-fips-builder
USER 0

RUN dnf install -y openssh-clients && dnf clean all

WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
# Dependencies come from uv.lock, not from a fresh resolve. `pip install .`
# read only pyproject.toml, whose floors carry no upper bound, so the image
# shipped whatever had been released that morning -- a dependency set no test
# had ever run against (RT#1564, the mcp-gemini google-genai 3.0 outage).
# --no-deps stops pip re-resolving what the lock already decided. This stays
# single-stage because dnf/openssh-clients are needed at runtime, so the
# project install and pip/dnf cleanup must happen before pip is removed.
COPY --from=lock /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt
COPY pyproject.toml README.md ./
COPY src/ ./src/
# pip is only needed to build the venv. Its vendored certifi, urllib3, msgpack
# and setuptools are what Trivy flags in this image, so both copies go.
RUN pip install --no-cache-dir --no-deps . && \
    pip uninstall -y pip && \
    if rpm -qf /usr/lib/python3*/site-packages/pip >/dev/null 2>&1; then \
        dnf remove -y "$(rpm -qf --qf '%{NAME}\n' /usr/lib/python3*/site-packages/pip)"; \
    fi && \
    rm -rf /usr/lib/python3*/site-packages/pip /usr/lib/python3*/site-packages/pip-*.dist-info && \
    dnf clean all

LABEL name="shiva" \
      version="1.0.2" \
      summary="Mass SSH client: run one shell command on many hosts in parallel" \
      maintainer="crunchtools.com" \
      url="https://github.com/crunchtools/shiva" \
      org.opencontainers.image.source="https://github.com/crunchtools/shiva" \
      org.opencontainers.image.description="Mass SSH client" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENTRYPOINT ["shiva"]
