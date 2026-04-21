package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"live-narrator/api"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

var wsUpgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// WSMessage は WebSocket の JSON 制御メッセージです。
type WSMessage struct {
	Version   int                    `json:"version"`
	Type      string                 `json:"type"`
	SessionID string                 `json:"session_id,omitempty"`
	RequestID string                 `json:"request_id,omitempty"`
	ClientID  string                 `json:"client_id,omitempty"`
	Model     string                 `json:"model,omitempty"`
	Prompt    string                 `json:"prompt,omitempty"`
	Text      string                 `json:"text,omitempty"`
	Role      string                 `json:"role,omitempty"`
	Encoding  string                 `json:"encoding,omitempty"`
	Chunk     string                 `json:"chunk,omitempty"`
	Data      string                 `json:"data,omitempty"`
	Done      bool                   `json:"done,omitempty"`
	Error     string                 `json:"error,omitempty"`
	Think     *bool                  `json:"think,omitempty"`
	Meta      map[string]interface{} `json:"meta,omitempty"`
}

type wsSession struct {
	server    *Server
	conn      *websocket.Conn
	modelName string
	sessionID string
	clientID  string
	version   int
	writeCh   chan []byte
	doneCh    chan struct{}
}

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := wsUpgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("websocket upgrade failed: %v", err)
		return
	}

	sess := &wsSession{
		server:  s,
		conn:    conn,
		version: 1,
		writeCh: make(chan []byte, 32),
		doneCh:  make(chan struct{}),
	}
	defer func() {
		close(sess.doneCh)
		_ = conn.Close()
	}()

	go sess.writeLoop()
	sess.readLoop(r.Context())
}

func (s *wsSession) readLoop(parentCtx context.Context) {
	defer func() {
		close(s.writeCh)
	}()

	_ = s.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	s.conn.SetPongHandler(func(string) error {
		return s.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	})

	for {
		messageType, payload, err := s.conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				return
			}
			log.Printf("websocket read error: %v", err)
			return
		}

		if messageType == websocket.BinaryMessage {
			s.handleBinaryMessage(payload)
			continue
		}

		var msg WSMessage
		if err := json.Unmarshal(payload, &msg); err != nil {
			s.sendError("invalid_json", err.Error(), "")
			continue
		}
		if msg.Version == 0 {
			msg.Version = 1
		}

		s.handleControl(parentCtx, &msg)
	}
}

func (s *wsSession) handleBinaryMessage(payload []byte) {
	if len(payload) == 0 {
		return
	}
	decoded := string(payload)
	if strings.HasPrefix(decoded, "base64:") {
		if _, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(decoded, "base64:")); err != nil {
			s.sendError("invalid_binary_payload", err.Error(), "")
		}
		return
	}

	// 現時点では Raw Binary の受け口を確保するだけにする。
	s.sendJSON(WSMessage{
		Version: s.version,
		Type:    "media.audio_chunk.ack",
		Meta: map[string]interface{}{
			"bytes": len(payload),
		},
	})
}

func (s *wsSession) handleControl(parentCtx context.Context, msg *WSMessage) {
	switch msg.Type {
	case "control.start_session":
		if strings.TrimSpace(msg.SessionID) != "" {
			s.sessionID = msg.SessionID
		}
		if strings.TrimSpace(msg.ClientID) != "" {
			s.clientID = msg.ClientID
		}
		s.sendJSON(WSMessage{
			Version:   s.version,
			Type:      "control.session_started",
			SessionID: s.sessionID,
			ClientID:  s.clientID,
		})
	case "control.end_session":
		s.sendJSON(WSMessage{Version: s.version, Type: "control.session_ending", SessionID: s.sessionID})
		return
	case "heartbeat.ping":
		s.sendJSON(WSMessage{Version: s.version, Type: "heartbeat.pong", SessionID: s.sessionID})
	case "inference.request":
		sessionID := s.sessionID
		if strings.TrimSpace(msg.SessionID) != "" {
			sessionID = msg.SessionID
		}
		prompt := strings.TrimSpace(msg.Prompt)
		if prompt == "" {
			prompt = strings.TrimSpace(msg.Text)
		}
		if prompt == "" {
			s.sendError("empty_prompt", "prompt が空です", msg.RequestID)
			return
		}
		go s.streamChat(parentCtx, msg, sessionID, prompt)
	default:
		s.sendError("unknown_type", fmt.Sprintf("unknown message type: %s", msg.Type), msg.RequestID)
	}
}

func (s *wsSession) streamChat(parentCtx context.Context, msg *WSMessage, sessionID, prompt string) {
	ctx, cancel := context.WithTimeout(parentCtx, 45*time.Second)
	defer cancel()

	think := false
	if msg.Think != nil {
		think = *msg.Think
	}
	if msg.Meta != nil {
		if v, ok := msg.Meta["think"].(bool); ok {
			think = v
		}
	}

	// 推論の安定性のため、セッション履歴は短いテキストに畳み込んでプロンプトへ渡す。
	historyPrefix := make([]string, 0, 8)
	if strings.TrimSpace(sessionID) != "" {
		if saved, ok := s.server.sessionHistory.Load(sessionID); ok {
			if history, ok := saved.([]HistoryEntry); ok {
				// 履歴が長くなりすぎるとレイテンシ悪化するため、後方のみ利用する。
				if len(history) > 8 {
					history = history[len(history)-8:]
				}
				for _, h := range history {
					role := strings.TrimSpace(h.Role)
					if role == "" || strings.TrimSpace(h.Text) == "" {
						continue
					}
					historyPrefix = append(historyPrefix, fmt.Sprintf("[%s] %s", role, h.Text))
				}
			}
		}
	}

	combinedPrompt := prompt
	if len(historyPrefix) > 0 {
		combinedPrompt = strings.Join(historyPrefix, "\n") + "\n[User] " + prompt
	}

	modelName := strings.TrimSpace(msg.Model)
	if modelName == "" {
		modelName = s.server.settings.DefaultModel
	}

	genReq := &api.GenerateRequest{
		Model:  modelName,
		Prompt: combinedPrompt,
		Think:  think,
		Stream: true,
		Options: map[string]interface{}{
			"num_predict": 192,
		},
	}

	if strings.TrimSpace(sessionID) != "" {
		if saved, ok := s.server.sessionContexts.Load(sessionID); ok {
			if ctxTokens, ok := saved.([]int); ok {
				genReq.Context = s.server.capContext(ctxTokens)
			}
		}
	}

	respChan, errChan, streamCancel, err := s.server.ollamaClient.GenerateStream(ctx, genReq)
	if err != nil {
		s.sendError("ollama_stream_error", err.Error(), msg.RequestID)
		return
	}
	defer streamCancel()

	var assistantBuilder strings.Builder
	var lastContext []int

	for {
		select {
		case <-ctx.Done():
			s.sendError("timeout", "推論タイムアウト", msg.RequestID)
			return
		case err, ok := <-errChan:
			if !ok {
				// error チャネルのクローズは正常終了でも発生するため、
				// response チャネル側の close(inference.done送信) を優先する。
				continue
			}
			if err != nil {
				s.sendError("ollama_stream_error", err.Error(), msg.RequestID)
				return
			}
		case genResp, ok := <-respChan:
			if !ok {
				if strings.TrimSpace(sessionID) != "" {
					if len(lastContext) > 0 {
						s.server.sessionContexts.Store(sessionID, s.server.capContext(lastContext))
					}
					assistantText := strings.TrimSpace(assistantBuilder.String())
					if assistantText != "" {
						s.server.appendSessionHistory(sessionID, prompt, assistantText)
					} else {
						log.Printf("ws stream completed with empty assistant response; session=%s request=%s", sessionID, msg.RequestID)
					}
				}
				s.sendJSON(WSMessage{
					Version:   s.version,
					Type:      "inference.done",
					SessionID: sessionID,
					RequestID: msg.RequestID,
					Done:      true,
				})
				return
			}

			if len(genResp.Context) > 0 {
				lastContext = genResp.Context
			}
			if think && strings.TrimSpace(genResp.Thinking) != "" {
				s.sendJSON(WSMessage{
					Version:   s.version,
					Type:      "inference.thinking",
					SessionID: sessionID,
					RequestID: msg.RequestID,
					Text:      genResp.Thinking,
				})
			}

			delta := genResp.Response
			if delta == "" {
				continue
			}
			assistantBuilder.WriteString(delta)
			s.sendJSON(WSMessage{
				Version:   s.version,
				Type:      "inference.delta",
				SessionID: sessionID,
				RequestID: msg.RequestID,
				Text:      delta,
			})
		}
	}
}

func (s *wsSession) sendJSON(msg WSMessage) {
	data, err := json.Marshal(msg)
	if err != nil {
		log.Printf("failed to marshal ws message: %v", err)
		return
	}
	select {
	case s.writeCh <- data:
	case <-s.doneCh:
	}
}

func (s *wsSession) sendError(code, message, requestID string) {
	s.sendJSON(WSMessage{
		Version:   s.version,
		Type:      "error",
		SessionID: s.sessionID,
		RequestID: requestID,
		Error:     code + ": " + message,
	})
}

func (s *wsSession) writeLoop() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case payload, ok := <-s.writeCh:
			if !ok {
				return
			}
			_ = s.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := s.conn.WriteMessage(websocket.TextMessage, payload); err != nil {
				log.Printf("websocket write error: %v", err)
				return
			}
		case <-ticker.C:
			_ = s.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := s.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				log.Printf("websocket ping error: %v", err)
				return
			}
		case <-s.doneCh:
			return
		}
	}
}
