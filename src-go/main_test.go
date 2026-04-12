package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"live-narrator/api"
	"live-narrator/processor"
)

// mockOllama はテスト用に api.OllamaAPI を実装します
type mockOllama struct {
	genResp *api.GenerateResponse
	genErr  error

	respChan chan *api.GenerateResponse
	errChan  chan error
}

func (m *mockOllama) Generate(ctx context.Context, req *api.GenerateRequest) (*api.GenerateResponse, error) {
	return m.genResp, m.genErr
}

func (m *mockOllama) GenerateStream(ctx context.Context, req *api.GenerateRequest) (<-chan *api.GenerateResponse, <-chan error, context.CancelFunc, error) {
	// チャネルが提供されていない場合、簡易的なストリームを作成
	if m.respChan == nil {
		rc := make(chan *api.GenerateResponse, 4)
		ec := make(chan error, 1)
		go func() {
			defer close(rc)
			defer close(ec)
			rc <- &api.GenerateResponse{Response: "chunk1", Context: []int{1}}
			time.Sleep(5 * time.Millisecond)
			rc <- &api.GenerateResponse{Response: "chunk2", Context: []int{2}}
		}()
		m.respChan = rc
		m.errChan = ec
	}

	cancel := func() {
		// ベストエフォートでクローズ
		defer func() { recover() }()
		select {
		case <-ctx.Done():
		default:
		}
		// チャネルを閉じる（既に閉じられていても安全に無視）
		go func() {
			defer func() { recover() }()
			if m.respChan != nil {
				close(m.respChan)
			}
			if m.errChan != nil {
				close(m.errChan)
			}
		}()
	}

	// NOTE: テスト内の短い Sleep は非決定的なタイミング依存を招く可能性があります。
	// TODO: より堅牢な同期（チャネル・ヒント）に置き換えることを検討してください。

	return m.respChan, m.errChan, cancel, nil
}

func TestHandleHealth_Success(t *testing.T) {
	s := &Server{ollamaClient: &mockOllama{genResp: &api.GenerateResponse{Response: "ok"}}}
	req := httptest.NewRequest("GET", "/health", nil)
	w := httptest.NewRecorder()
	s.handleHealth(w, req)

	res := w.Result()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 got %d", res.StatusCode)
	}
	var body map[string]interface{}
	if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode body: %v", err)
	}
	if ok, _ := body["ok"].(bool); !ok {
		t.Fatalf("expected ok true, got %v", body)
	}
}

func TestHandleGenerate_NonStreaming(t *testing.T) {
	tp := processor.NewTextProcessor()
	mock := &mockOllama{genResp: &api.GenerateResponse{Response: "mocked response", Context: []int{1, 2, 3}}}
	s := &Server{ollamaClient: mock, textProcessor: tp}

	payload := `{"model":"live-narrator","prompt":"hello","parameters":{}}`
	req := httptest.NewRequest("POST", "/generate", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	s.handleGenerate(w, req)

	res := w.Result()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 got %d", res.StatusCode)
	}

	var env ResponseEnvelope
	if err := json.NewDecoder(res.Body).Decode(&env); err != nil {
		t.Fatalf("failed to decode response envelope: %v", err)
	}
	if env.Response != "mocked response" {
		t.Fatalf("unexpected response: %s", env.Response)
	}
	if len(env.Context) != 3 {
		t.Fatalf("unexpected context length: %v", env.Context)
	}
}

func TestHandleGenerateStream(t *testing.T) {
	tp := processor.NewTextProcessor()
	// ストリーミングチャネルを持つモックを準備
	mock := &mockOllama{}
	s := &Server{ollamaClient: mock, textProcessor: tp}

	payload := `{"model":"live-narrator","prompt":"stream","parameters":{}}`
	req := httptest.NewRequest("POST", "/generate/stream", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	s.handleGenerateStream(w, req)

	res := w.Result()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 got %d", res.StatusCode)
	}

	body := w.Body.String()
	lines := strings.Split(strings.TrimSpace(body), "\n")
	if len(lines) < 2 {
		t.Fatalf("expected multiple NDJSON lines, got: %q", body)
	}

	// 1 行目は初期エンベロープ、以降の行はストリームチャンク
	var chunk api.GenerateResponse
	if err := json.Unmarshal([]byte(lines[1]), &chunk); err != nil {
		t.Fatalf("failed to unmarshal chunk: %v; line: %s", err, lines[1])
	}
	if chunk.Response == "" {
		t.Fatalf("expected chunk response, got empty")
	}
}
