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

// OllamaClient は Ollama サーバーとの通信を処理します
type OllamaClient struct {
	client  *http.Client // HTTP クライアント
	baseURL string       // Ollama サーバーのベースURL
}

// OllamaAPI はサーバーで使用されるメソッドを定義し、テストでモック可能にします
type OllamaAPI interface {
	Generate(ctx context.Context, req *GenerateRequest) (*GenerateResponse, error)                                                // 応答を生成
	GenerateStream(ctx context.Context, req *GenerateRequest) (<-chan *GenerateResponse, <-chan error, context.CancelFunc, error) // ストリーム応答を生成
}

// GenerateRequest は Ollama の生成エンドポイントへのリクエストを表します
type GenerateRequest struct {
	Model   string                 `json:"model"`             // 使用するモデル名
	Prompt  string                 `json:"prompt"`            // 入力プロンプト
	System  string                 `json:"system,omitempty"`  // システム設定（オプション）
	Stream  bool                   `json:"stream,omitempty"`  // ストリームモード
	Options map[string]interface{} `json:"options,omitempty"` // 追加オプション
	Context []int                  `json:"context,omitempty"` // コンテキスト情報
	Think   bool                   `json:"think"`             // 思考モード（false も必ず送信）
}

// GenerateResponse は Ollama からの応答を表します
type GenerateResponse struct {
	Response  string      `json:"response"`           // 応答内容
	Model     string      `json:"model"`              // 使用されたモデル名
	CreatedAt string      `json:"created_at"`         // 応答生成日時
	Done      bool        `json:"done"`               // 応答が完了したかどうか
	Context   []int       `json:"context,omitempty"`  // コンテキスト情報
	Thinking  string      `json:"thinking,omitempty"` // 思考過程（オプション）
	Usage     *TokenUsage `json:"usage,omitempty"`    // トークン使用量
}

// TokenUsage はトークン使用情報を表します
type TokenUsage struct {
	PromptTokens     int `json:"prompt_tokens,omitempty"`     // プロンプトで使用されたトークン数
	CompletionTokens int `json:"completion_tokens,omitempty"` // 応答生成で使用されたトークン数
	TotalTokens      int `json:"total_tokens,omitempty"`      // 合計トークン数
}

// NewOllamaClient は接続プーリングを備えた Ollama クライアントを作成します
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

// Generate は非ストリーミングのリクエストを Ollama に送り、応答を返します
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

	// レスポンス本文をすべて読み込みデコードを試みます。Ollama は非ストリーミングでも
	// NDJSON（複数の JSON 行）を返すことがあるため、まず通常の JSON として解析し、
	// 失敗した場合は最後の有効な JSON 行を使用します。
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	var genResp GenerateResponse
	if err := json.Unmarshal(bodyBytes, &genResp); err == nil {
		return &genResp, nil
	}

	// NDJSON として解析を試み、最後の有効な JSON オブジェクトを採用
	// NOTE: Ollama のレスポンスが NDJSON になる場合に対応しています。
	// TODO: 必要に応じて NDJSON の解析ロジックを検証し、エッジケース（空行・部分的な行）に対処してください。
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

// GenerateStream はストリーミングリクエストを Ollama に送り、チャネル経由で応答を返します
// 戻り値: 応答チャネル、エラーチャネル、キャンセル関数
func (oc *OllamaClient) GenerateStream(ctx context.Context, req *GenerateRequest) (
	<-chan *GenerateResponse, <-chan error, context.CancelFunc, error,
) {
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
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		return nil, nil, nil, fmt.Errorf("ollama returned %d: %s", resp.StatusCode, string(body))
	}

	// ストリーミング用のコンテキストを作成（キャンセル可能）
	streamCtx, cancel := context.WithCancel(ctx)

	// チャネルを作成
	responseChan := make(chan *GenerateResponse, 10)
	errorChan := make(chan error, 1)

	// ストリーミング応答を読み取るゴルーチンを開始
	go func() {
		defer close(responseChan)
		defer close(errorChan)
		defer resp.Body.Close()

		scanner := bufio.NewScanner(resp.Body)
		// 行読み取り効率を上げるためバッファを拡張
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

// buildRequest は Ollama への HTTP リクエストを構築します
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
