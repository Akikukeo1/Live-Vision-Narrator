.PHONY: build clean run test

# Build the Go binary
build:
	go build -o engine .

# Run the server
run: build
	./engine

# Clean build artifacts
clean:
	rm -f engine

# Run tests
test:
	go test -v ./...

# Format code
fmt:
	go fmt ./...

# Lint
lint:
	golint ./...

# Dependencies
deps:
	go mod download
	go mod tidy

# Development target with hot reload (requires air)
dev:
	air

.PHONY: cross-build-linux cross-build-windows

# Cross-compile for Linux
cross-build-linux:
	GOOS=linux GOARCH=amd64 go build -o engine_linux .

# Cross-compile for Windows
cross-build-windows:
	GOOS=windows GOARCH=amd64 go build -o engine.exe .
