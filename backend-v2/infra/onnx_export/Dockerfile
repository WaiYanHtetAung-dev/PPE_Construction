ARG EXPORT_BASE
FROM ${EXPORT_BASE}
COPY requirements.lock /build/requirements.lock
COPY wheels/ /build/wheels/
RUN --network=none python -m pip install --no-index --require-hashes --find-links=/build/wheels -r /build/requirements.lock
USER 10001:10001
