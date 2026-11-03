# my-pa is a terminal CLI, not a long-running server. This image installs the
# `mypa` entry point so CI can smoke-test it with `docker run --rm <image>`.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md MANIFEST.in ./
COPY mypa ./mypa
COPY mypa.example.jsonc ./

RUN pip install --no-cache-dir .

ENTRYPOINT ["mypa"]
CMD ["--help"]
