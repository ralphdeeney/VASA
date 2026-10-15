FROM golang:1.25.0-bookworm@sha256:81dc45d05a7444ead8c92a389621fafabc8e40f8fd1a19d7e5df14e61e98bc1a AS build
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo-dev libwebp-dev && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 builder && mkdir /build && chown -R builder:builder /build /go
USER builder
WORKDIR /build
ENV GOMAXPROCS=2
COPY --chown=builder:builder go.mod go.sum ./
COPY --chown=builder:builder vasa-host-trust.pem ./
ENV SSL_CERT_FILE=/build/vasa-host-trust.pem
RUN go mod download && go mod verify
COPY --chown=builder:builder . .
RUN go test -p 2 ./pkg/call/... && go vet -p 2 ./pkg/call/... && CGO_ENABLED=1 go build -p 2 -ldflags "-X main.version=0.7.2-rekovi-calls.1-vasa" -o server ./cmd/evolution-go

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tzdata ffmpeg libjpeg62-turbo libwebp7 poppler-utils && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 vasa && mkdir -p /app/dbdata /app/logs && chown -R vasa:vasa /app
WORKDIR /app
COPY --from=build --chown=vasa:vasa /build/server /app/server
COPY --from=build --chown=vasa:vasa /build/manager/dist /app/manager/dist
COPY --from=build --chown=vasa:vasa /build/VERSION /app/VERSION
COPY --from=build /build/LICENSE /build/NOTICE /build/TRADEMARKS.md /app/notices/
COPY --from=build /build/vasa-host-trust.pem /usr/local/share/vasa-host-trust.pem
USER 1000:1000
ENV GIN_MODE=release TZ=UTC
ENV SSL_CERT_FILE=/usr/local/share/vasa-host-trust.pem
ENTRYPOINT ["/app/server"]
