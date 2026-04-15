// @title Live-Narrator API
// @version 1.0
// @description Live-Vision-Narrator の API ドキュメント
// @host localhost:8000
// @BasePath /
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"live-narrator/api"
	"live-narrator/config"
	"live-narrator/processor"
	"live-narrator/util"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	_ "live-narrator/docs"

	httpSwagger "github.com/swaggo/http-swagger"
)

// サーバーは共有リソースを保持します
type Server struct {
	settings        *config.Settings
	ollamaClient    api.OllamaAPI
	aivisClient     *api.AivisClient
	textProcessor   *processor.TextProcessor
	sessionContexts sync.Map // セッションIDに関連付けられたコンテキスト
	sessionHistory  sync.Map // セッションIDに関連付けられた会話履歴
}

// HistoryEntry は会話履歴のエントリを表します
type HistoryEntry struct {
	Role string `json:"role"` // 発言者の役割（例: ユーザー、システム）
	Text string `json:"text"` // 発言内容
}

// SessionRequest はセッション操作のリクエストボディです
type SessionRequest struct {
	SessionID string `json:"session_id"` // セッションID
}

// GenerateRequestBody は Python API リクエスト形式に一致します
type GenerateRequestBody struct {
	Model      string                 `json:"model"`      // 使用するモデル名
	Prompt     string                 `json:"prompt"`     // 入力プロンプト
	Parameters map[string]interface{} `json:"parameters"` // モデルに渡す追加パラメータ
	SessionID  string                 `json:"session_id"` // セッションID
}

// ResponseEnvelope はレスポンスデータをメタデータと共にラップします
type ResponseEnvelope struct {
	Response  string         `json:"response"`             // モデルの応答
	Thinking  string         `json:"thinking,omitempty"`   // モデルの思考過程（オプション）
	Tokens    map[string]int `json:"tokens,omitempty"`     // トークン使用量
	ElapsedMs float64        `json:"elapsed_ms,omitempty"` // 経過時間（ミリ秒）
	Context   []int          `json:"context,omitempty"`    // コンテキスト情報
	Error     string         `json:"error,omitempty"`      // エラーメッセージ（オプション）
}

// capContext は古いトークンを捨て、最新側のコンテキストだけを保持します。
// max<=0 の場合は上限なしとして扱います。
func (s *Server) capContext(ctx []int) []int {
	if len(ctx) == 0 {
		return ctx
	}

	max := 0
	if s.settings != nil {
		max = s.settings.MaxContextTokens
	}
	if max <= 0 || len(ctx) <= max {
		return ctx
	}

	start := len(ctx) - max
	trimmed := make([]int, max)
	copy(trimmed, ctx[start:])
	return trimmed
}

func main() {
	settings := config.LoadSettings()

	// クライアントを初期化
	ollamaClient := api.NewOllamaClient(settings.OllamaURL)
	aivisClient := api.NewAivisClient("") // Aivis の URL が設定されていればここで指定
	textProcessor := processor.NewTextProcessor()

	server := &Server{
		settings:      settings,
		ollamaClient:  ollamaClient,
		aivisClient:   aivisClient,
		textProcessor: textProcessor,
	}

	// HTTP ルートを設定
	http.HandleFunc("/health", server.handleHealth)
	http.HandleFunc("/generate", server.handleGenerate)
	http.HandleFunc("/generate/stream", server.handleGenerateStream)
	http.HandleFunc("/models", server.handleModels)
	http.HandleFunc("/session/reset", server.handleSessionReset)
	http.HandleFunc("/session/get", server.handleSessionGet)

	// Swagger UI を提供 (/swagger/)
	http.Handle("/swagger/", httpSwagger.WrapHandler)
	// いくつかの環境で /swagger へのルートが必要なためリダイレクトを追加
	http.HandleFunc("/swagger", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/swagger/", http.StatusMovedPermanently)
	})
	// 明示的に index.html パスも登録
	http.Handle("/swagger/index.html", httpSwagger.WrapHandler)

	// サーバーを起動
	addr := fmt.Sprintf("%s:%d", settings.HostIP, settings.APIPort)
	log.Printf("Starting server on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}

// handleHealth は Ollama への接続確認を行います
// Health check
// @Summary Health check
// @Description Check connectivity to Ollama
// @Tags health
// @Produce json
// @Success 200 {object} map[string]interface{}
// @Failure 503 {object} map[string]interface{}
// @Router /health [get]
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	_, err := s.ollamaClient.Generate(ctx, &api.GenerateRequest{
		Model:  s.settings.DefaultModel,
		Prompt: "test",
		Stream: false,
	})

	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		if err := json.NewEncoder(w).Encode(map[string]interface{}{
			"ok":    false,
			"error": err.Error(),
		}); err != nil {
			log.Printf("failed to encode health error response: %v", err)
		}
		return
	}

	if err := json.NewEncoder(w).Encode(map[string]interface{}{
		"ok": true,
	}); err != nil {
		log.Printf("failed to encode health response: %v", err)
	}
}

// handleGenerate は非ストリーミングのテキスト生成を処理します
// Generate plain text response
// @Summary Generate text (non-stream)
// @Description 非ストリーミングでテキストを生成します。
// @Tags generate
// @Accept json
// @Produce json
// @Param body body GenerateRequestBody true "Generate request"
// @Success 200 {object} ResponseEnvelope
// @Failure 400 {object} map[string]string
// @Failure 500 {object} map[string]string
// @Router /generate [post]
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
		if err := json.NewEncoder(w).Encode(map[string]string{"error": err.Error()}); err != nil {
			log.Printf("failed to encode request decode error response: %v", err)
		}
		return
	}
	profiler.Mark("req_decoded")

	// Ollama リクエストを構築
	ollamaReq := &api.GenerateRequest{
		Model:  req.Model,
		Prompt: req.Prompt,
	}

	if req.Parameters != nil {
		if think, ok := req.Parameters["think"].(bool); ok {
			ollamaReq.Think = think
		}

		var systemOverride string
		if value, ok := req.Parameters["system_override"].(string); ok {
			systemOverride = strings.TrimSpace(value)
		}

		var systemProfile string
		if value, ok := req.Parameters["system_profile"].(string); ok {
			systemProfile = strings.TrimSpace(value)
		}

		if systemOverride != "" {
			ollamaReq.System = systemOverride
		} else if systemProfile != "" {
			log.Printf("ignoring system_profile %q because profiles must be resolved to prompt text before setting GenerateRequest.System", systemProfile)
		}
	}

	// 保存されたセッションコンテキストがあれば取得
	if req.SessionID != "" {
		if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
			ollamaReq.Context = s.capContext(saved.([]int))
		}
	}

	profiler.Mark("ollama_req_built")

	// Ollama を呼び出す
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()

	genResp, err := s.ollamaClient.Generate(ctx, ollamaReq)
	profiler.Mark("ollama_response_received")

	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		if err := json.NewEncoder(w).Encode(map[string]string{"error": err.Error()}); err != nil {
			log.Printf("failed to encode internal error response: %v", err)
		}
		return
	}

	// レスポンスを処理
	profiler.Mark("processing_start")
	revealThoughts := false
	if req.Parameters != nil {
		if reveal, ok := req.Parameters["reveal_thoughts"].(bool); ok {
			revealThoughts = reveal
		}
	}

	cleanedResponse := s.textProcessor.SanitizeResponse(genResp.Response, revealThoughts)
	profiler.Mark("processing_end")

	// セッションのコンテキストと会話履歴を保存
	if req.SessionID != "" {
		if len(genResp.Context) > 0 {
			s.sessionContexts.Store(req.SessionID, s.capContext(genResp.Context))
		}
		history := []HistoryEntry{
			{Role: "user", Text: req.Prompt},
			{Role: "assistant", Text: cleanedResponse},
		}
		s.sessionHistory.Store(req.SessionID, history)
	}

	// レスポンスを構築
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
	// TODO: 本番ではプロファイルログの出力レベルや形式を設定可能にすることを検討してください

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(envelope); err != nil {
		log.Printf("failed to encode response envelope: %v", err)
	}
}

// handleGenerateStream はストリーミング生成を処理します
// Stream generation (NDJSON)
// @Summary Generate stream (NDJSON)
// @Description POST ボディを受け取り NDJSON を逐次返します。各行は JSON チャンクです（最初の行は elapsed info）。
// @Tags generate
// @Accept json
// @Produce application/x-ndjson
// @Param body body GenerateRequestBody true "Generate stream request"
// @Success 200 {string} string "NDJSON stream"
// @Failure 400 {object} map[string]string
// @Router /generate/stream [post]
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
		if err := json.NewEncoder(w).Encode(map[string]string{"error": err.Error()}); err != nil {
			log.Printf("failed to encode stream request decode error response: %v", err)
		}
		return
	}
	profiler.Mark("req_decoded")

	// Ollama リクエストを構築
	ollamaReq := &api.GenerateRequest{
		Model:  req.Model,
		Prompt: req.Prompt,
	}

	if req.Parameters != nil {
		if think, ok := req.Parameters["think"].(bool); ok {
			ollamaReq.Think = think
		}

		if systemOverride, ok := req.Parameters["system_override"].(string); ok && strings.TrimSpace(systemOverride) != "" {
			ollamaReq.System = systemOverride
		} else if systemProfile, ok := req.Parameters["system_profile"].(string); ok && strings.TrimSpace(systemProfile) != "" {
			ollamaReq.System = systemProfile
		}
	}

	// 保存されたセッションコンテキストがあれば取得
	if req.SessionID != "" {
		if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
			ollamaReq.Context = s.capContext(saved.([]int))
		}
	}

	profiler.Mark("ollama_req_built")

	// ストリーミングで応答を受信
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()

	respChan, errChan, streamCancel, err := s.ollamaClient.GenerateStream(ctx, ollamaReq)
	profiler.Mark("ollama_stream_started")

	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		if err := json.NewEncoder(w).Encode(map[string]string{"error": err.Error()}); err != nil {
			log.Printf("failed to encode stream internal error response: %v", err)
		}
		return
	}
	defer streamCancel()

	// レスポンスストリームのヘッダを準備
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	// タイミング情報を含むヘッダを送信
	elapsedHeader := ResponseEnvelope{
		ElapsedMs: profiler.GetDelta("start", "ollama_stream_started"),
	}
	if data, err := json.Marshal(elapsedHeader); err == nil {
		if _, err := w.Write(append(data, '\n')); err != nil {
			log.Printf("failed to write elapsed header: %v", err)
		}
	}

	// Ollama からのストリーム行を逐次処理
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

			// レスポンスを処理
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

			// チャンクを送信
			// ストリーミングでは UI が `tokens` フィールドを参照するため、
			// 完了チャンク（genResp.Done==true）で `usage` を `tokens` 形式に変換して付与します。
			// 互換性のため `usage` 自体は残しますが、UI は `tokens` を優先できるようになります。
			if genResp.Done && genResp.Usage != nil {
				// ジェネリックなマップに変換してから `tokens` を注入する
				var chunkMap map[string]interface{}
				if b, err := json.Marshal(genResp); err == nil {
					if err := json.Unmarshal(b, &chunkMap); err == nil {
						chunkMap["tokens"] = map[string]int{
							"prompt_tokens":     genResp.Usage.PromptTokens,
							"completion_tokens": genResp.Usage.CompletionTokens,
							"total_tokens":      genResp.Usage.TotalTokens,
						}
						if data, err := json.Marshal(chunkMap); err == nil {
							if _, err := w.Write(append(data, '\n')); err != nil {
								log.Printf("failed to write stream chunk: %v", err)
							}
						} else {
							log.Printf("failed to marshal chunkMap: %v", err)
						}
					} else {
						// マップ変換に失敗したら元の構造体をそのまま送信
						if data, err := json.Marshal(genResp); err == nil {
							if _, err := w.Write(append(data, '\n')); err != nil {
								log.Printf("failed to write stream chunk: %v", err)
							}
						}
					}
				} else {
					// マーシャル失敗時は元の構造体を送信
					if data, err := json.Marshal(genResp); err == nil {
						if _, err := w.Write(append(data, '\n')); err != nil {
							log.Printf("failed to write stream chunk: %v", err)
						}
					}
				}
			} else {
				// 通常のチャンクはそのまま送信
				if data, err := json.Marshal(genResp); err == nil {
					if _, err := w.Write(append(data, '\n')); err != nil {
						log.Printf("failed to write stream chunk: %v", err)
					}
				}
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

	// セッションコンテキストと会話履歴を保存
	if req.SessionID != "" {
		if lastContext != nil {
			s.sessionContexts.Store(req.SessionID, s.capContext(lastContext))
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

// handleModels は利用可能なモデル一覧を返します
// Models list
// @Summary List models
// @Description Return the list of available models
// @Tags models
// @Produce json
// @Success 200 {object} map[string]interface{}
// @Router /models [get]
func (s *Server) handleModels(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(map[string]interface{}{
		"models": []string{},
	}); err != nil {
		log.Printf("failed to encode models response: %v", err)
	}
}

// handleSessionReset はセッション状態をリセットします
// Reset session
// @Summary Reset session context and history
// @Description Reset stored context and history for a session
// @Tags session
// @Accept json
// @Produce json
// @Param body body SessionRequest true "Reset session request body"
// @Success 200 {object} map[string]interface{}
// @Router /session/reset [post]
func (s *Server) handleSessionReset(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		SessionID string `json:"session_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	s.sessionContexts.Delete(req.SessionID)
	s.sessionHistory.Delete(req.SessionID)

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":         true,
		"session_id": req.SessionID,
	}); err != nil {
		log.Printf("failed to encode session reset response: %v", err)
	}
}

// handleSessionGet はセッションデータを取得します
// Get session
// @Summary Get session context and history
// @Description Retrieve stored context and history for a session
// @Tags session
// @Accept json
// @Produce json
// @Param body body SessionRequest true "Get session request body"
// @Success 200 {object} map[string]interface{}
// @Router /session/get [post]
func (s *Server) handleSessionGet(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		SessionID string `json:"session_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	var context []int
	var history []HistoryEntry

	if saved, ok := s.sessionContexts.Load(req.SessionID); ok {
		context = saved.([]int)
	}

	if saved, ok := s.sessionHistory.Load(req.SessionID); ok {
		history = saved.([]HistoryEntry)
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(map[string]interface{}{
		"ok":             true,
		"session_id":     req.SessionID,
		"has_context":    context != nil,
		"context_length": len(context),
		"history_length": len(history),
		"history":        history,
		"context":        context,
	}); err != nil {
		log.Printf("failed to encode session get response: %v", err)
	}
}
