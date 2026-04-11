.PHONY: build clean run test

# Build the Go binary into bin/ (source under src-go)
build:
	go build -o bin/narrator_engine ./src-go

# Run the server (uses built binary)
run: build
	./bin/narrator_engine

# Clean build artifacts
clean:
	-rm -f bin/narrator_engine bin/narrator_engine.exe

# Run tests (run tests in src-go)
test:
	go test -v ./src-go/...

# Format code (src-go)
fmt:
	go fmt ./src-go/...

# Lint (src-go)
lint:
	golint ./src-go/...

# Dependencies
deps:
	cd src-go && go mod download && go mod tidy

# Development target with hot reload (requires air)
dev:
	cd src-go && air

.PHONY: cross-build-linux cross-build-windows

# Cross-compile for Linux
cross-build-linux:
	GOOS=linux GOARCH=amd64 go build -o bin/narrator_engine_linux ./src-go

# Cross-compile for Windows
cross-build-windows:
	GOOS=windows GOARCH=amd64 go build -o bin/narrator_engine.exe ./src-go
