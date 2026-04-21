package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"live-narrator/config"
)

const maxAudioChunkBytes = 1024 * 1024

type ingestResult struct {
	PartialText string
	FinalText   string
	CacheBytes  int
	CacheChunks int
}

type sttCache struct {
	Parts     []string
	Bytes     int
	Chunks    int
	UpdatedAt time.Time
}

// STTService は音声チャンク受信とテキストキャッシュ制御を担当します。
type STTService struct {
	settings   *config.Settings
	httpClient *http.Client
	mu         sync.Mutex
	cache      map[string]*sttCache
}

func NewSTTService(settings *config.Settings) *STTService {
	return &STTService{
		settings: settings,
		httpClient: &http.Client{
			Timeout: 3 * time.Second,
		},
		cache: make(map[string]*sttCache),
	}
}

func (s *STTService) Ingest(ctx context.Context, sessionID, userID, codec string, payload []byte, final bool) (*ingestResult, error) {
	if strings.TrimSpace(sessionID) == "" {
		sessionID = "default"
	}
	if strings.TrimSpace(userID) == "" {
		userID = "unknown"
	}
	if strings.TrimSpace(codec) == "" {
		codec = "opus"
	}

	cacheKey := sessionID + ":" + userID
	partial, err := s.transcribeChunk(ctx, sessionID, userID, codec, payload, false)
	if err != nil {
		log.Printf("stt partial transcribe error: session=%s user=%s err=%v", sessionID, userID, err)
	}

	s.mu.Lock()
	entry := s.cache[cacheKey]
	if entry == nil {
		entry = &sttCache{}
		s.cache[cacheKey] = entry
	}
	entry.UpdatedAt = time.Now()
	entry.Chunks++
	entry.Bytes += len(payload)
	if strings.TrimSpace(partial) != "" {
		if len(entry.Parts) == 0 || entry.Parts[len(entry.Parts)-1] != partial {
			entry.Parts = append(entry.Parts, partial)
		}
	}
	result := &ingestResult{
		PartialText: partial,
		CacheBytes:  entry.Bytes,
		CacheChunks: entry.Chunks,
	}

	if final {
		finalText := strings.TrimSpace(strings.Join(entry.Parts, " "))
		if finalText == "" {
			finalText = ""
		}
		delete(s.cache, cacheKey)
		result.FinalText = finalText
	}
	s.mu.Unlock()

	return result, nil
}

func (s *STTService) transcribeChunk(ctx context.Context, sessionID, userID, codec string, payload []byte, final bool) (string, error) {
	if s.settings == nil || strings.TrimSpace(s.settings.STTEndpoint) == "" {
		// STTバックエンド未接続時はダミー結果で配管のみ検証可能にする。
		if len(payload) == 0 {
			return "", nil
		}
		return fmt.Sprintf("chunk_%d", len(payload)), nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.settings.STTEndpoint, io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("X-Audio-Codec", codec)
	req.Header.Set("X-Session-ID", sessionID)
	req.Header.Set("X-User-ID", userID)
	if final {
		req.Header.Set("X-Final", "1")
	}
	if apiKey, err := s.settings.ResolveSTTAPIKey(); err == nil {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}

	resp, err := s.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("stt endpoint status %d", resp.StatusCode)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(body, &parsed); err == nil {
		if text, ok := parsed["text"].(string); ok {
			return strings.TrimSpace(text), nil
		}
	}
	return strings.TrimSpace(string(body)), nil
}

func (s *Server) handleSTTIngest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	sessionID := strings.TrimSpace(r.URL.Query().Get("session_id"))
	userID := strings.TrimSpace(r.URL.Query().Get("user_id"))
	codec := strings.TrimSpace(r.Header.Get("X-Audio-Codec"))
	final := strings.EqualFold(strings.TrimSpace(r.URL.Query().Get("final")), "true") || r.URL.Query().Get("final") == "1"

	body := http.MaxBytesReader(w, r.Body, maxAudioChunkBytes)
	defer body.Close()
	payload, err := io.ReadAll(body)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"error": "invalid audio payload"})
		return
	}

	start := time.Now()
	result, err := s.sttService.Ingest(r.Context(), sessionID, userID, codec, payload, final)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"error": "stt ingest failed"})
		return
	}

	elapsed := time.Since(start).Milliseconds()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":           true,
		"partial_text": result.PartialText,
		"final_text":   result.FinalText,
		"cache_bytes":  result.CacheBytes,
		"cache_chunks": result.CacheChunks,
		"elapsed_ms":   elapsed,
	}); err != nil {
		log.Printf("failed to encode stt ingest response: %v", err)
	}
}
