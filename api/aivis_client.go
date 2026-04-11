package api

import (
	"context"
	"net/http"
	"time"
)

// AivisClient handles communication with Aivis server for voice synthesis
type AivisClient struct {
	client  *http.Client
	baseURL string
}

// NewAivisClient creates a new Aivis client
func NewAivisClient(baseURL string) *AivisClient {
	transport := &http.Transport{
		MaxIdleConns:        50,
		MaxIdleConnsPerHost: 5,
		IdleConnTimeout:     90 * time.Second,
		DisableKeepAlives:   false,
	}

	client := &http.Client{
		Timeout:   30 * time.Second,
		Transport: transport,
	}

	return &AivisClient{
		client:  client,
		baseURL: baseURL,
	}
}

// SynthesisRequest represents a text-to-speech synthesis request
type SynthesisRequest struct {
	Text string `json:"text"`
}

// SynthesisResponse represents a TTS response
type SynthesisResponse struct {
	Status string `json:"status"`
	URL    string `json:"url,omitempty"`
	Error  string `json:"error,omitempty"`
}

// Synthesize sends text to Aivis for voice synthesis (non-blocking, returns immediately)
func (ac *AivisClient) Synthesize(ctx context.Context, text string) error {
	if ac.baseURL == "" {
		// Aivis not configured, skip
		return nil
	}

	// Fire-and-forget async call in background
	go func() {
		ctxWithTimeout, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		// Placeholder: actual implementation would POST to Aivis endpoint
		// For now, just log
		_ = ctxWithTimeout
		_ = text
	}()

	return nil
}

// Close closes the HTTP client
func (ac *AivisClient) Close() error {
	ac.client.CloseIdleConnections()
	return nil
}
