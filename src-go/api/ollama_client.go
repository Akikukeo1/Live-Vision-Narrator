package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// OllamaClient handles communication with Ollama server
type OllamaClient struct {
	client  *http.Client
	baseURL string
}

// OllamaAPI defines the methods used by the server and allows mocking in tests.
type OllamaAPI interface {
	Generate(ctx context.Context, req *GenerateRequest) (*GenerateResponse, error)
	GenerateStream(ctx context.Context, req *GenerateRequest) (<-chan *GenerateResponse, <-chan error, context.CancelFunc, error)
}

// GenerateRequest represents a request to the Ollama generate endpoint
type GenerateRequest struct {
	Model   string                 `json:"model"`
	Prompt  string                 `json:"prompt"`
	System  string                 `json:"system,omitempty"`
	Stream  bool                   `json:"stream,omitempty"`
	Options map[string]interface{} `json:"options,omitempty"`
	Context []int                  `json:"context,omitempty"`
	Think   bool                   `json:"think,omitempty"`
}

// GenerateResponse represents a response from Ollama
type GenerateResponse struct {
	Response  string      `json:"response"`
	Model     string      `json:"model"`
	CreatedAt string      `json:"created_at"`
	Done      bool        `json:"done"`
	Context   []int       `json:"context,omitempty"`
	Thinking  string      `json:"thinking,omitempty"`
	Usage     *TokenUsage `json:"usage,omitempty"`
}

// TokenUsage represents token usage information
type TokenUsage struct {
	PromptTokens     int `json:"prompt_tokens,omitempty"`
	CompletionTokens int `json:"completion_tokens,omitempty"`
	TotalTokens      int `json:"total_tokens,omitempty"`
}

// NewOllamaClient creates a new Ollama client with connection pooling
func NewOllamaClient(baseURL string) *OllamaClient {
	transport := &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 10,
		IdleConnTimeout:     90 * time.Second,
		DisableKeepAlives:   false,
		DisableCompression:  false,
	}

	client := &http.Client{
		Timeout:   60 * time.Second,
		Transport: transport,
	}

	return &OllamaClient{
		client:  client,
		baseURL: baseURL,
	}
}

// Generate sends a non-streaming request to Ollama and returns the response
func (oc *OllamaClient) Generate(ctx context.Context, req *GenerateRequest) (*GenerateResponse, error) {
	req.Stream = false

	httpReq, err := oc.buildRequest(ctx, req)
	if err != nil {
		return nil, err
	}

	resp, err := oc.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("ollama request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("ollama returned %d: %s", resp.StatusCode, string(body))
	}

	// Read whole body and try to decode. Ollama may return NDJSON (multiple JSON lines)
	// even for non-streaming requests; prefer decoding a single JSON, otherwise
	// fall back to taking the last non-empty JSON line.
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	var genResp GenerateResponse
	if err := json.Unmarshal(bodyBytes, &genResp); err == nil {
		return &genResp, nil
	}

	// Try parsing as NDJSON and take the last valid JSON object
	lines := bytes.Split(bytes.TrimSpace(bodyBytes), []byte("\n"))
	for i := len(lines) - 1; i >= 0; i-- {
		line := bytes.TrimSpace(lines[i])
		if len(line) == 0 {
			continue
		}
		if err := json.Unmarshal(line, &genResp); err == nil {
			return &genResp, nil
		}
	}

	return nil, fmt.Errorf("failed to decode response (tried JSON and NDJSON)")
}

// GenerateStream sends a streaming request to Ollama and yields responses via channel
// Returns: channel of responses, error channel, close function
func (oc *OllamaClient) GenerateStream(ctx context.Context, req *GenerateRequest) (
	<-chan *GenerateResponse, <-chan error, context.CancelFunc, error) {

	req.Stream = true

	httpReq, err := oc.buildRequest(ctx, req)
	if err != nil {
		return nil, nil, nil, err
	}

	resp, err := oc.client.Do(httpReq)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("ollama stream request failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		return nil, nil, nil, fmt.Errorf("ollama returned %d: %s", resp.StatusCode, string(body))
	}

	// Create context for streaming (allows cancellation)
	streamCtx, cancel := context.WithCancel(ctx)

	// Create channels
	responseChan := make(chan *GenerateResponse, 10)
	errorChan := make(chan error, 1)

	// Start goroutine to read streaming response
	go func() {
		defer close(responseChan)
		defer close(errorChan)
		defer resp.Body.Close()

		scanner := bufio.NewScanner(resp.Body)
		// Set a larger buffer for efficient line reading
		buf := make([]byte, 0, 64*1024)
		scanner.Buffer(buf, 1024*1024)

		for scanner.Scan() {
			select {
			case <-streamCtx.Done():
				return
			default:
			}

			line := scanner.Bytes()
			if len(line) == 0 {
				continue
			}

			var genResp GenerateResponse
			if err := json.Unmarshal(line, &genResp); err != nil {
				errorChan <- fmt.Errorf("failed to decode stream line: %w", err)
				return
			}

			select {
			case responseChan <- &genResp:
			case <-streamCtx.Done():
				return
			}
		}

		if err := scanner.Err(); err != nil {
			errorChan <- fmt.Errorf("stream reader error: %w", err)
		}
	}()

	return responseChan, errorChan, cancel, nil
}

// buildRequest constructs an HTTP request to Ollama
func (oc *OllamaClient) buildRequest(ctx context.Context, req *GenerateRequest) (*http.Request, error) {
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	url := oc.baseURL + "/api/generate"
	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		return nil, err
	}

	httpReq.ContentLength = int64(len(payload))
	httpReq.Header.Set("Content-Type", "application/json")

	return httpReq, nil
}
