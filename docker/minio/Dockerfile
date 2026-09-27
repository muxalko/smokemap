# syntax=docker/dockerfile:1

# MinIO withdrew its community images (Docker Hub and Quay) and release
# binaries (dl.min.io) when it archived the open-source server and client.
# Rebuild the pinned releases from their archived source tags with the build
# flags of upstream's Makefile and the layout of upstream's Dockerfile.release.
# The toolchains match the Go runtime reported by the withdrawn release images.
#
# Compose passes the release tag and the commit that tag must resolve to.

FROM golang:1.24.5-alpine@sha256:daae04ebad0c21149979cd8e9db38f565ecefd8547cf4a591240dc1972cf1399 AS server-build
ARG SERVER_RELEASE
ARG SERVER_COMMIT
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN apk add --no-cache git
WORKDIR /src
RUN : "${SERVER_RELEASE:?}" "${SERVER_COMMIT:?}" \
 && git init -q . \
 && git fetch -q --depth 1 https://github.com/minio/minio.git "refs/tags/${SERVER_RELEASE}" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "${SERVER_COMMIT}"
RUN go mod download && go mod verify
RUN version=$(echo "${SERVER_RELEASE}" | sed 's#^RELEASE\.\(.*\)T\([0-9]*\)-\([0-9]*\)-\([0-9]*\)Z$#\1T\2:\3:\4Z#') \
 && ldflags=$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "${version}") \
 && go build -tags kqueue -trimpath -ldflags "${ldflags}" -o /out/minio \
 && /out/minio --version | grep -F "version ${SERVER_RELEASE} (commit-id=${SERVER_COMMIT})"

FROM golang:1.24.6-alpine@sha256:c8c5f95d64aa79b6547f3b626eb84b16a7ce18a139e3e9ca19a8c078b85ba80d AS client-build
ARG CLIENT_RELEASE
ARG CLIENT_COMMIT
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN apk add --no-cache git
WORKDIR /src
RUN : "${CLIENT_RELEASE:?}" "${CLIENT_COMMIT:?}" \
 && git init -q . \
 && git fetch -q --depth 1 https://github.com/minio/mc.git "refs/tags/${CLIENT_RELEASE}" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "${CLIENT_COMMIT}"
RUN go mod download && go mod verify
RUN version=$(echo "${CLIENT_RELEASE}" | sed 's#^RELEASE\.\(.*\)T\([0-9]*\)-\([0-9]*\)-\([0-9]*\)Z$#\1T\2:\3:\4Z#') \
 && ldflags=$(MC_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "${version}") \
 && go build -tags kqueue -trimpath -ldflags "${ldflags}" -o /out/mc \
 && /out/mc --version | grep -F "version ${CLIENT_RELEASE} (commit-id=${CLIENT_COMMIT})"

# Upstream copied a static curl into ubi-micro for the healthcheck; the minimal
# image ships curl itself.
FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6@sha256:34880b64c07f28f64d95737f82f891516de9a3b43583f39970f7bf8e4cfa48b7 AS server
ARG SERVER_RELEASE
ARG SERVER_COMMIT
LABEL name="MinIO" \
      version="${SERVER_RELEASE}" \
      release="${SERVER_RELEASE}" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="${SERVER_COMMIT}"
ENV MINIO_ACCESS_KEY_FILE=access_key \
    MINIO_SECRET_KEY_FILE=secret_key \
    MINIO_ROOT_USER_FILE=access_key \
    MINIO_ROOT_PASSWORD_FILE=secret_key \
    MINIO_KMS_SECRET_KEY_FILE=kms_master_key \
    MINIO_UPDATE_MINISIGN_PUBKEY="RWTx5Zr1tiHQLwG9keckT0c45M3AGeHD6IvimQHpyRywVWGbP1aVSGav" \
    MINIO_CONFIG_ENV_FILE=config.env \
    MC_CONFIG_DIR=/tmp/.mc
COPY --from=server-build /out/minio /usr/bin/minio
COPY --from=server-build /src/dockerscripts/docker-entrypoint.sh /usr/bin/docker-entrypoint.sh
COPY --from=server-build /src/CREDITS /src/LICENSE /licenses/
EXPOSE 9000
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/docker-entrypoint.sh"]
CMD ["minio"]

FROM registry.access.redhat.com/ubi9/ubi-micro:9.6@sha256:990002083442f6a93cd3249da32ecb7c3f6be778a1bec3a73a9c17fbc40edc15 AS client
ARG CLIENT_RELEASE
ARG CLIENT_COMMIT
LABEL version="${CLIENT_RELEASE}" \
      release="${CLIENT_RELEASE}" \
      org.opencontainers.image.source="https://github.com/minio/mc" \
      org.opencontainers.image.revision="${CLIENT_COMMIT}"
COPY --from=registry.access.redhat.com/ubi9/ubi-minimal:9.6@sha256:34880b64c07f28f64d95737f82f891516de9a3b43583f39970f7bf8e4cfa48b7 \
     /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /etc/pki/ca-trust/extracted/pem/
COPY --from=client-build /out/mc /usr/bin/mc
COPY --from=client-build /src/CREDITS /src/LICENSE /licenses/
ENTRYPOINT ["mc"]
