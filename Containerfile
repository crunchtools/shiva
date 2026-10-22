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

FROM quay.io/hummingbird/python:3.14-fips-builder
USER 0

RUN dnf install -y openssh-clients && dnf clean all

WORKDIR /app
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

LABEL name="shiva" \
      version="1.0.0" \
      summary="Mass SSH client: run one shell command on many hosts in parallel" \
      maintainer="crunchtools.com" \
      url="https://github.com/crunchtools/shiva" \
      org.opencontainers.image.source="https://github.com/crunchtools/shiva" \
      org.opencontainers.image.description="Mass SSH client" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENTRYPOINT ["shiva"]
