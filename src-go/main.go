package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"live-narrator/api"
	"live-narrator/config"
	"live-narrator/processor"
	"live-narrator/util"
)

// Server holds shared resources
type Server struct {
	settings        *config.Settings
	ollamaClient    api.OllamaAPI
	aivisClient     *api.AivisClient
	textProcessor   *processor.TextProcessor
	sessionContexts sync.Map // map[string][]int
	sessionHistory  sync.Map // map[string][]HistoryEntry
}

// HistoryEntry represents a conversation history entry
type HistoryEntry struct {
	Role string `json:"role"`
	Text string `json:"text"`
}

// GenerateRequestBody matches the Python API request format
type GenerateRequestBody struct {
	Model      string                 `json:"model"`
	Prompt     string                 `json:"prompt"`
	Parameters map[string]interface{} `json:"parameters"`
	SessionID  string                 `json:"session_id"`
}

// ResponseEnvelope wraps response data with metadata
type ResponseEnvelope struct {
	Response  string         `json:"response"`
	Thinking  string         `json:"thinking,omitempty"`
	Tokens    map[string]int `json:"tokens,omitempty"`
	ElapsedMs float64        `json:"elapsed_ms,omitempty"`
	Context   []int          `json:"context,omitempty"`
	Error     string         `json:"error,omitempty"`
}

func main() {
	settings := config.LoadSettings()
	unusedVar := "this should fail go vet"

	// Initialize clients
	ollamaClient := api.NewOllamaClient(settings.OllamaURL)
	aivisClient := api.NewAivisClient("") // Aivis URL from config if available
	textProcessor := processor.NewTextProcessor()

	server := &Server{
		settings:      settings,
		ollamaClient:  ollamaClient,
		aivisClient:   aivisClient,
		textProcessor: textProcessor,
	}

	// Setup HTTP routes
						http.HandleFunc("/health", server.handleHealth)
	http.HandleFunc("/generate", server.handleGenerate)
	http.HandleFunc("/generate/stream", server.handleGenerateStream)
	http.HandleFunc("/models", server.handleModels)
	http.HandleFunc("/session/reset", server.handleSessionReset)
	http.HandleFunc("/session/get", server.handleSessionGet)

	// Start server
	addr := fmt.Sprintf("%s:%d", settings.HostIP, settings.APIPort)
	log.Printf("Starting server on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}

// handleHealth checks connectivity to Ollama
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	_, err := s.ollamaClient.Generate(ctx, &api.GenerateRequest{
		Model:  "test",
		Prompt: "test",
		Stream: false,
	})

	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"ok":    false,
			"error": err.Error(),
		})
		return
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"ok": true,
	})
}

// handleGenerate handles non-streaming text generation
func (s *Server) handleGenerate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	profiler := util.NewProfiler(true)
	profiler.Mark("start")

	var req GenerateRequestBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	profiler.Mark("req_decoded")

	// Build Ollama request
	ollamaReq := &api.GenerateRequest{
		Model:  req.Model,
		Prompt: req.Prompt,
	}

	if req.Parameters != nil {
		if think, ok := req.Parameters["think"].(bool); ok {
			ollamaReq.Think = think
		}
	}

	// Retrieve session context if available
	if req.SessionID != "" {
		if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
			ollamaReq.Context = saved.([]int)
		}
	}

	profiler.Mark("ollama_req_built")

	// Call Ollama
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()

	genResp, err := s.ollamaClient.Generate(ctx, ollamaReq)
	profiler.Mark("ollama_response_received")

	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	// Process response
	profiler.Mark("processing_start")
	revealThoughts := false
	if req.Parameters != nil {
		if reveal, ok := req.Parameters["reveal_thoughts"].(bool); ok {
			revealThoughts = reveal
		}
	}

	cleanedResponse := s.textProcessor.SanitizeResponse(genResp.Response, revealThoughts)
	profiler.Mark("processing_end")

	// Save session context and history
	if req.SessionID != "" {
		if len(genResp.Context) > 0 {
			s.sessionContexts.Store(req.SessionID, genResp.Context)
		}
		history := []HistoryEntry{
			{Role: "user", Text: req.Prompt},
			{Role: "assistant", Text: cleanedResponse},
		}
		s.sessionHistory.Store(req.SessionID, history)
	}

	// Build response
	envelope := ResponseEnvelope{
		Response:  cleanedResponse,
		ElapsedMs: profiler.GetDelta("start", "processing_end"),
		Context:   genResp.Context,
	}

	if revealThoughts && genResp.Thinking != "" {
		envelope.Thinking = genResp.Thinking
	}

	if genResp.Usage != nil {
		envelope.Tokens = map[string]int{
			"prompt_tokens":     genResp.Usage.PromptTokens,
			"completion_tokens": genResp.Usage.CompletionTokens,
			"total_tokens":      genResp.Usage.TotalTokens,
		}
	}

	profiler.Mark("response_built")
	log.Printf("PROFILE /generate A_recv=%.2fms B_recv_to_preToken=%.2fms total=%.2fms",
		profiler.GetDelta("ollama_req_built", "ollama_response_received"),
		profiler.GetDelta("ollama_response_received", "processing_start"),
		profiler.GetDelta("start", "response_built"))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(envelope)
}

// handleGenerateStream handles streaming text generation
func (s *Server) handleGenerateStream(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	profiler := util.NewProfiler(true)
	profiler.Mark("start")

	var req GenerateRequestBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	profiler.Mark("req_decoded")

	// Build Ollama request
	ollamaReq := &api.GenerateRequest{
		Model:  req.Model,
		Prompt: req.Prompt,
	}

	if req.Parameters != nil {
		if think, ok := req.Parameters["think"].(bool); ok {
			ollamaReq.Think = think
		}
	}

	// Retrieve session context if available
	if req.SessionID != "" {
		if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
			ollamaReq.Context = saved.([]int)
		}
	}

	profiler.Mark("ollama_req_built")

	// Stream response
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()

	respChan, errChan, streamCancel, err := s.ollamaClient.GenerateStream(ctx, ollamaReq)
	profiler.Mark("ollama_stream_started")

	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	defer streamCancel()

	// Prepare response stream
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	// Send header with timing info
	elapsedHeader := ResponseEnvelope{
		ElapsedMs: profiler.GetDelta("start", "ollama_stream_started"),
	}
	if data, err := json.Marshal(elapsedHeader); err == nil {
		w.Write(append(data, '\n'))
	}

	// Stream lines from Ollama
	revealThoughts := false
	if req.Parameters != nil {
		if reveal, ok := req.Parameters["reveal_thoughts"].(bool); ok {
			revealThoughts = reveal
		}
	}

	profiler.Mark("streaming_start")
	var assistantParts []string
	var lastContext []int
	firstChunk := true

	for {
		select {
		case genResp, ok := <-respChan:
			if !ok {
				goto streamEnd
			}

			if firstChunk {
				profiler.Mark("first_chunk")
				firstChunk = false
				log.Printf("PROFILE /generate/stream first_chunk=%.2fms",
					profiler.GetDelta("streaming_start", "first_chunk"))
			}

			// Process response
			if genResp.Response != "" {
				cleaned := s.textProcessor.SanitizeResponse(genResp.Response, revealThoughts)
				assistantParts = append(assistantParts, cleaned)
				genResp.Response = cleaned
			}

			if !revealThoughts {
				genResp.Thinking = ""
			}

			if len(genResp.Context) > 0 {
				lastContext = genResp.Context
			}

			// Send chunk
			if data, err := json.Marshal(genResp); err == nil {
				w.Write(append(data, '\n'))
			}

			if flusher, ok := w.(http.Flusher); ok {
				flusher.Flush()
			}

		case err := <-errChan:
			log.Printf("Stream error: %v", err)
			goto streamEnd

		case <-ctx.Done():
			goto streamEnd
		}
	}

streamEnd:
	profiler.Mark("streaming_end")

	// Save session context and history
	if req.SessionID != "" {
		if lastContext != nil {
			s.sessionContexts.Store(req.SessionID, lastContext)
		}
		if len(assistantParts) > 0 {
			assistantText := strings.Join(assistantParts, "")
			history := []HistoryEntry{
				{Role: "user", Text: req.Prompt},
				{Role: "assistant", Text: assistantText},
			}
			s.sessionHistory.Store(req.SessionID, history)
		}
	}

	log.Printf("PROFILE /generate/stream A_recv=%.2fms B_recv_to_preToken=%.2fms total=%.2fms",
		profiler.GetDelta("ollama_req_built", "ollama_stream_started"),
		profiler.GetDelta("ollama_stream_started", "streaming_start"),
		profiler.GetDelta("start", "streaming_end"))
}

// handleModels lists available models
func (s *Server) handleModels(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"models": []string{},
	})
}

// handleSessionReset resets session state
func (s *Server) handleSessionReset(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		SessionID string `json:"session_id"`
	}
	json.NewDecoder(r.Body).Decode(&req)

	s.sessionContexts.Delete(req.SessionID)
	s.sessionHistory.Delete(req.SessionID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":         true,
		"session_id": req.SessionID,
	})
}

// handleSessionGet retrieves session data
func (s *Server) handleSessionGet(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		SessionID string `json:"session_id"`
	}
	json.NewDecoder(r.Body).Decode(&req)

	var context []int
	var history []HistoryEntry

	if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
		context = saved.([]int)
	}

	if saved, ok := s.sessionHistory.Load(req.SessionID); ok {
		history = saved.([]HistoryEntry)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":             true,
		"session_id":     req.SessionID,
		"has_context":    context != nil,
		"context_length": len(context),
		"history_length": len(history),
		"history":        history,
		"context":        context,
	})
}
