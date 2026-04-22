package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"live-narrator/config"
	"log"
	"net/http"
	"os/exec"
	"strings"
	"sync"
	"time"
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
	decMu      sync.Mutex
	decoders   map[string]*opusDecoder
}

func NewSTTService(settings *config.Settings) *STTService {
	return &STTService{
		settings: settings,
		httpClient: &http.Client{
			Timeout: 3 * time.Second,
		},
		cache:    make(map[string]*sttCache),
		decoders: make(map[string]*opusDecoder),
	}
}

// opusDecoder は ffmpeg を使って受信 Opus を PCM に変換し、
// 生成された PCM を一定サイズごとに STT に流すワーカーです。
type opusDecoder struct {
	s         *STTService
	sessionID string
	userID    string

	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser

	chunkBytes int

	mu  sync.Mutex
	buf bytes.Buffer

	wg     sync.WaitGroup
	closed bool
	// final transcription captured when STTUseSingleFinal is enabled
	finalText string
	finalErr  error
}

// TODO: STTUseSingleFinalの値やチャンク送信/一括送信の分岐状況をデバッグ出力する

func (d *opusDecoder) Write(p []byte) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.closed {
		return fmt.Errorf("decoder closed")
	}
	if d.stdin == nil {
		return fmt.Errorf("decoder stdin nil")
	}
	_, err := d.stdin.Write(p)
	return err
}

func (d *opusDecoder) Close() error {
	d.mu.Lock()
	if d.closed {
		d.mu.Unlock()
		return nil
	}
	d.closed = true
	if d.stdin != nil {
		_ = d.stdin.Close()
	}
	d.mu.Unlock()
	d.wg.Wait()
	if d.cmd != nil {
		_ = d.cmd.Wait()
	}
	return nil
}

func (d *opusDecoder) run() {
	defer d.wg.Done()
	buf := make([]byte, 4096)
	for {
		n, err := d.stdout.Read(buf)
		if n > 0 {
			d.mu.Lock()
			d.buf.Write(buf[:n])
			// デフォルト動作: チャンクを切り出して非同期で STT に送る
			if d.s != nil && d.s.settings != nil && d.s.settings.STTUseSingleFinal {
				// STTUseSingleFinal の場合は部分送信せず、全データをバッファするだけ
				log.Printf("[DEBUG] STTUseSingleFinal有効: チャンク送信せずバッファのみ session=%s user=%s", d.sessionID, d.userID)
			} else {
				log.Printf("[DEBUG] チャンク送信モード: チャンクごとにSTT送信 session=%s user=%s", d.sessionID, d.userID)
				for d.buf.Len() >= d.chunkBytes {
					chunk := make([]byte, d.chunkBytes)
					_, _ = d.buf.Read(chunk)
					d.mu.Unlock()
					// 非同期で処理してキャッシュを更新
					go func(ch []byte) {
						if partial, err := d.s.transcribeChunk(context.Background(), d.sessionID, d.userID, "pcm_s16le", ch, false); err == nil {
							d.s.updateCacheWithPartial(d.sessionID, d.userID, partial, len(ch))
						} else {
							log.Printf("stt partial transcribe error: session=%s user=%s err=%v", d.sessionID, d.userID, err)
						}
					}(chunk)
					d.mu.Lock()
				}
			}
			d.mu.Unlock()
		}
		if err != nil {
			if err != io.EOF {
				log.Printf("opusDecoder read error: %v", err)
			}
			break
		}
	}

	// stdout が閉じられたら残りを final として送る
	d.mu.Lock()
	remaining := d.buf.Bytes()
	d.buf.Reset()
	d.mu.Unlock()

	if d.s != nil && d.s.settings != nil && d.s.settings.STTUseSingleFinal {
		// 一括送信モード: 溜めた PCM を一回で送信し、finalText を保存する
		if len(remaining) > 0 {
			log.Printf("[DEBUG] STTUseSingleFinal一括送信: session=%s user=%s bytes=%d", d.sessionID, d.userID, len(remaining))
			txt, terr := d.s.transcribeChunk(context.Background(), d.sessionID, d.userID, "pcm_s16le", remaining, true)
			if terr != nil {
				log.Printf("stt final transcribe error: session=%s user=%s err=%v", d.sessionID, d.userID, terr)
			}
			d.finalText = txt
			d.finalErr = terr
		} else {
			log.Printf("[DEBUG] STTUseSingleFinal一括送信(残りなし): session=%s user=%s", d.sessionID, d.userID)
			txt, terr := d.s.transcribeChunk(context.Background(), d.sessionID, d.userID, "pcm_s16le", nil, true)
			if terr != nil {
				log.Printf("stt final transcribe error: session=%s user=%s err=%v", d.sessionID, d.userID, terr)
			}
			d.finalText = txt
			d.finalErr = terr
		}
	} else {
		if len(remaining) > 0 {
			if partial, err := d.s.transcribeChunk(context.Background(), d.sessionID, d.userID, "pcm_s16le", remaining, true); err == nil {
				d.s.updateCacheWithPartial(d.sessionID, d.userID, partial, len(remaining))
			} else {
				log.Printf("stt final transcribe error: session=%s user=%s err=%v", d.sessionID, d.userID, err)
			}
		} else {
			// 残りが無くても final フラグで通知する
			if partial, err := d.s.transcribeChunk(context.Background(), d.sessionID, d.userID, "pcm_s16le", nil, true); err == nil {
				d.s.updateCacheWithPartial(d.sessionID, d.userID, partial, 0)
			} else {
				log.Printf("stt final transcribe error: session=%s user=%s err=%v", d.sessionID, d.userID, err)
			}
		}
	}
}

func (s *STTService) updateCacheWithPartial(sessionID, userID, partial string, addedBytes int) {
	cacheKey := sessionID + ":" + userID
	s.mu.Lock()
	defer s.mu.Unlock()
	entry := s.cache[cacheKey]
	if entry == nil {
		entry = &sttCache{}
		s.cache[cacheKey] = entry
	}
	entry.UpdatedAt = time.Now()
	entry.Chunks++
	entry.Bytes += addedBytes
	if strings.TrimSpace(partial) != "" {
		if len(entry.Parts) == 0 || entry.Parts[len(entry.Parts)-1] != partial {
			entry.Parts = append(entry.Parts, partial)
		}
	}
}

func (s *STTService) getOrCreateDecoder(sessionID, userID string) (*opusDecoder, error) {
	key := sessionID + ":" + userID
	s.decMu.Lock()
	dec := s.decoders[key]
	s.decMu.Unlock()
	if dec != nil {
		return dec, nil
	}

	// デフォルトのチャンク長(ms)
	chunkMS := 200
	if s.settings != nil && s.settings.ChunkMS > 0 {
		chunkMS = s.settings.ChunkMS
	}
	chunkBytes := chunkMS * 32 // 16kHz * 2bytes * chunkMS/1000 = chunkMS*32

	cmd := exec.Command("ffmpeg", "-loglevel", "error", "-f", "opus", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1")
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		_ = stdin.Close()
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		_ = stdin.Close()
		return nil, err
	}

	dec = &opusDecoder{
		s:          s,
		sessionID:  sessionID,
		userID:     userID,
		cmd:        cmd,
		stdin:      stdin,
		stdout:     stdout,
		chunkBytes: chunkBytes,
	}
	dec.wg.Add(1)
	go dec.run()

	s.decMu.Lock()
	s.decoders[key] = dec
	s.decMu.Unlock()
	return dec, nil
}

func (s *STTService) stopDecoder(sessionID, userID string) (string, error) {
	key := sessionID + ":" + userID
	s.decMu.Lock()
	dec := s.decoders[key]
	if dec != nil {
		delete(s.decoders, key)
	}
	s.decMu.Unlock()
	if dec == nil {
		return "", nil
	}
	// Close will wait for run() to finish and populate finalText if configured
	if err := dec.Close(); err != nil {
		return "", err
	}
	return dec.finalText, dec.finalErr
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
	var partial string
	var err error

	// TODO: STTUseSingleFinalの値をデバッグ出力
	log.Printf("[DEBUG] Ingest: STTUseSingleFinal=%v session=%s user=%s codec=%s final=%v", s.settings != nil && s.settings.STTUseSingleFinal, sessionID, userID, codec, final)
	// Opus は長時間ストリームとして処理する。decoder があれば書き込み、なければフォールバックで同期処理する。
	if strings.EqualFold(codec, "opus") {
		if !final {
			if len(payload) > 0 {
				dec, derr := s.getOrCreateDecoder(sessionID, userID)
				if derr == nil && dec != nil {
					if werr := dec.Write(payload); werr != nil {
						// 書けない場合は同期で送る
						log.Printf("[DEBUG] デコーダ書き込み失敗 fallback同期送信 session=%s user=%s", sessionID, userID)
						if p, terr := s.transcribeChunk(ctx, sessionID, userID, codec, payload, false); terr == nil {
							partial = p
						} else {
							log.Printf("stt partial transcribe error: session=%s user=%s err=%v", sessionID, userID, terr)
						}
					}
				} else {
					// デコーダ生成失敗時は同期フォールバック
					log.Printf("[DEBUG] デコーダ生成失敗 fallback同期送信 session=%s user=%s", sessionID, userID)
					if p, terr := s.transcribeChunk(ctx, sessionID, userID, codec, payload, false); terr == nil {
						partial = p
					} else {
						log.Printf("stt partial transcribe error: session=%s user=%s err=%v", sessionID, userID, terr)
					}
				}
			}
		} else {
			// final: デコーダがあれば閉じてフラッシュ、なければ同期で final を送る
			// デコーダがない場合でも payload があればそれを final として送る
			log.Printf("[DEBUG] final受信: stopDecoder呼び出し session=%s user=%s", sessionID, userID)
			decFinalText, decErr := s.stopDecoder(sessionID, userID)
			if decErr != nil {
				log.Printf("stt: stopDecoder error: session=%s user=%s err=%v", sessionID, userID, decErr)
			}
			// デコーダが finalText を返した場合はそれを優先する（後で result.FinalText に適用）
			if decFinalText != "" {
				log.Printf("[DEBUG] stopDecoderからfinalText取得 session=%s user=%s text=%q", sessionID, userID, decFinalText)
				partial = decFinalText
			} else if len(payload) > 0 {
				log.Printf("[DEBUG] stopDecoderからfinalTextなし fallback同期送信 session=%s user=%s", sessionID, userID)
				if p, terr := s.transcribeChunk(ctx, sessionID, userID, codec, payload, true); terr == nil {
					partial = p
				} else {
					log.Printf("stt final transcribe error: session=%s user=%s err=%v", sessionID, userID, terr)
				}
			}
		}
	} else {
		// Opus 以外は従来どおり同期処理
		partial, err = s.transcribeChunk(ctx, sessionID, userID, codec, payload, false)
		if err != nil {
			log.Printf("stt partial transcribe error: session=%s user=%s err=%v", sessionID, userID, err)
		}
	}

	// キャッシュ更新はここで行う（decoder 側からも updateCacheWithPartial が入る）
	s.mu.Lock()
	entry := s.cache[cacheKey]
	if entry == nil {
		entry = &sttCache{}
		s.cache[cacheKey] = entry
	}
	entry.UpdatedAt = time.Now()
	entry.Chunks++
	entry.Bytes += len(payload)
	// デコーダ経由で partial が非同期に書き込まれる可能性があるため、
	// ここで取得できる最新のキャッシュ値を優先する。
	if strings.TrimSpace(partial) != "" {
		if len(entry.Parts) == 0 || entry.Parts[len(entry.Parts)-1] != partial {
			entry.Parts = append(entry.Parts, partial)
		}
	}
	// 直前にデコーダが更新している可能性があるので、最新のエントリから部分テキストを取り出す
	latestPartial := ""
	if len(entry.Parts) > 0 {
		latestPartial = entry.Parts[len(entry.Parts)-1]
	}
	result := &ingestResult{
		PartialText: latestPartial,
		CacheBytes:  entry.Bytes,
		CacheChunks: entry.Chunks,
	}

	if final {
		// 設定で一括送信モードが有効で、partial にデコーダからの最終文字列が入っている場合は
		// それを確定テキストとして採用する（キャッシュの結合を使わない）。
		if s.settings != nil && s.settings.STTUseSingleFinal && strings.TrimSpace(partial) != "" {
			result.FinalText = strings.TrimSpace(partial)
			delete(s.cache, cacheKey)
		} else {
			finalText := strings.TrimSpace(strings.Join(entry.Parts, " "))
			delete(s.cache, cacheKey)
			result.FinalText = finalText
		}
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

	// 受信した codec が opus の場合、可能であればローカルの ffmpeg を使って PCM (s16le, 16k, mono) に変換する。
	// ffmpeg が利用できない／変換に失敗した場合は元の payload をそのまま送る（既存の挙動）。
	if strings.EqualFold(codec, "opus") && len(payload) > 0 {
		// short timeout for decoding
		decCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		cmd := exec.CommandContext(decCtx, "ffmpeg", "-loglevel", "error", "-f", "opus", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1")
		cmd.Stdin = bytes.NewReader(payload)
		var out bytes.Buffer
		var serr bytes.Buffer
		cmd.Stdout = &out
		cmd.Stderr = &serr
		if err := cmd.Run(); err == nil {
			payload = out.Bytes()
			codec = "pcm_s16le"
			log.Printf("stt: decoded opus -> pcm_s16le (session=%s user=%s bytes=%d)", sessionID, userID, len(payload))
		} else {
			// ffmpeg の stderr をログに出す
			sstr := serr.String()
			if len(sstr) > 0 {
				// 長すぎる場合は短縮
				if len(sstr) > 1000 {
					sstr = sstr[:1000] + "..."
				}
				log.Printf("stt: ffmpeg decode failed: %v stderr=%s", err, sstr)
			} else {
				log.Printf("stt: ffmpeg decode failed: %v (no stderr)", err)
			}
			log.Printf("stt: ffmpeg decode failed, falling back to opus send")
		}
	}

	// 詳細ログ: STT エンドポイントへ送信する前に情報を出力
	log.Printf("stt: transcribeChunk session=%s user=%s codec=%s bytes=%d final=%v endpoint=%s",
		sessionID, userID, codec, len(payload), final, s.settings.STTEndpoint)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.settings.STTEndpoint, io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		return "", err
	}
	// Content-Type を codec によってわかりやすくセットする
	contentType := "application/octet-stream"
	switch strings.ToLower(codec) {
	case "pcm_s16le":
		contentType = "audio/L16; rate=16000; channels=1"
	case "opus":
		contentType = "audio/opus"
	}
	req.Header.Set("Content-Type", contentType)
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
		// エラーボディを短縮してログ
		bstr := string(body)
		if len(bstr) > 200 {
			bstr = bstr[:200] + "..."
		}
		log.Printf("stt: transcribeChunk error: status=%d body=%s", resp.StatusCode, bstr)
		return "", fmt.Errorf("stt endpoint status %d", resp.StatusCode)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(body, &parsed); err == nil {
		if text, ok := parsed["text"].(string); ok {
			t := strings.TrimSpace(text)
			log.Printf("stt: transcribeChunk success: session=%s user=%s text=%q", sessionID, userID, t)
			return t, nil
		}
		// JSON だが text フィールドが無い場合、レスポンスを短縮してログ
		bstr := string(body)
		if len(bstr) > 200 {
			bstr = bstr[:200] + "..."
		}
		log.Printf("stt: transcribeChunk json response (no text): %s", bstr)
	} else {
		// 非 JSON レスポンス
		bstr := string(body)
		if len(bstr) > 200 {
			bstr = bstr[:200] + "..."
		}
		log.Printf("stt: transcribeChunk raw response: %s", bstr)
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
