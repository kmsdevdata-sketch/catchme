FROM golang:1.24 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -o /out/app .

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/app /app
EXPOSE 8080
ENTRYPOINT ["/app"]
