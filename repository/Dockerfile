FROM python:3.14-slim AS documentation

ARG MKDOCS_VERSION=1.6.1

RUN python -m pip install --no-cache-dir "mkdocs==${MKDOCS_VERSION}"

WORKDIR /source
COPY README.md /source/README.md
COPY engulf-api/README.md /source/engulf-api/README.md
COPY engulf/README.md /source/engulf/README.md
COPY engulf-executable-wrapper-api/README.md /source/engulf-executable-wrapper-api/README.md
COPY engulf-executable-wrapper/README.md /source/engulf-executable-wrapper/README.md
COPY plugins/engulf-plugin-list/README.md /source/plugins/engulf-plugin-list/README.md
COPY examples/encryption-core/README.md /source/examples/encryption-core/README.md
COPY examples/encryption-app/README.md /source/examples/encryption-app/README.md
COPY repository/README.md /source/repository/README.md
COPY repository/mkdocs.yml /source/repository/mkdocs.yml

RUN mkdocs build \
    --strict \
    --config-file /source/repository/mkdocs.yml \
    --site-dir /site

FROM pypiserver/pypiserver:v2.4.1

ARG BLEACH_VERSION=6.2.0
ARG MARKDOWN_VERSION=3.8.2

RUN python -m pip install --no-cache-dir \
    "bleach==${BLEACH_VERSION}" \
    "markdown==${MARKDOWN_VERSION}"

COPY repository/gunicorn.conf.py /data/gunicorn.conf.py
COPY repository/repository_app.py /data/repository_app.py
COPY repository/package_docs.py /data/package_docs.py
COPY repository/welcome.html /data/welcome.html
COPY --from=documentation /site /data/docs

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, ssl, urllib.request; context = ssl.create_default_context(cafile='/data/tls/certificate.pem'); urllib.request.urlopen(f'https://{os.environ[\"HOSTNAME\"]}:8080/health', context=context, timeout=3).read()"]
