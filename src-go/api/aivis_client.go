package api

import (
	"context"
	"net/http"
	"time"
)

// AivisClient は音声合成のための Aivis サーバーとの通信を処理します
type AivisClient struct {
	client  *http.Client // HTTP クライアント
	baseURL string       // Aivis サーバーのベースURL
}

// NewAivisClient は新しい Aivis クライアントを作成します
func NewAivisClient(baseURL string) *AivisClient {
	transport := &http.Transport{
		MaxIdleConns:        50,               // 最大アイドル接続数
		MaxIdleConnsPerHost: 5,                // ホストごとの最大アイドル接続数
		IdleConnTimeout:     90 * time.Second, // アイドル接続のタイムアウト
		DisableKeepAlives:   false,            // Keep-Alive を無効化しない
	}

	client := &http.Client{
		Timeout:   30 * time.Second, // リクエストのタイムアウト
		Transport: transport,
	}

	return &AivisClient{
		client:  client,
		baseURL: baseURL,
	}
}

// SynthesisRequest はテキスト音声合成リクエストを表します
type SynthesisRequest struct {
	Text string `json:"text"` // 合成するテキスト
}

// SynthesisResponse は音声合成のレスポンスを表します
type SynthesisResponse struct {
	Status string `json:"status"`          // ステータス（例: 成功、失敗）
	URL    string `json:"url,omitempty"`   // 音声ファイルのURL（オプション）
	Error  string `json:"error,omitempty"` // エラーメッセージ（オプション）
}

// Synthesize はテキストを Aivis に送信して音声合成を行います（非同期で即時に戻ります）
func (ac *AivisClient) Synthesize(ctx context.Context, text string) error {
	if ac.baseURL == "" {
		// Aivis が設定されていない場合はスキップ
		return nil
	}

	// バックグラウンドで fire-and-forget の非同期呼び出し
	go func() {
		ctxWithTimeout, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		// プレースホルダ: 実際の実装では Aivis のエンドポイントに POST します
		// とりあえずログ等で代替します
		// TODO: 実運用ではここで Aivis エンドポイントへ POST し、レスポンスを処理する実装が必要です
		_ = ctxWithTimeout
		_ = text
	}()

	return nil
}

// Close は HTTP クライアントのアイドル接続を閉じます
func (ac *AivisClient) Close() error {
	ac.client.CloseIdleConnections()
	return nil
}
