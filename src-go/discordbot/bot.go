package discordbot

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/bwmarrin/discordgo"
)

// Options は Discord Bot の起動設定です。
type Options struct {
	Token                 string
	AllowedGuildID        string
	AllowedTextChannelID  string
	AllowedVoiceChannelID string
	CommandPrefix         string
	MinimalPostLength     int
	IngestURL             string
	GenerateURL           string
	Model                 string
	SilenceMS             int
}

type ingestResponse struct {
	OK          bool   `json:"ok"`
	PartialText string `json:"partial_text"`
	FinalText   string `json:"final_text"`
	CacheBytes  int    `json:"cache_bytes"`
	CacheChunks int    `json:"cache_chunks"`
	ElapsedMs   int64  `json:"elapsed_ms"`
}

type generateRequest struct {
	Model      string                 `json:"model"`
	Prompt     string                 `json:"prompt"`
	SessionID  string                 `json:"session_id"`
	Parameters map[string]interface{} `json:"parameters,omitempty"`
}

type generateResponse struct {
	Response string `json:"response"`
	Error    string `json:"error,omitempty"`
}

type voiceWorker struct {
	stopCh    chan struct{}
	channelID string
}

// Bot は API と疎結合な Discord 制御コンポーネントです。
type Bot struct {
	opts         Options
	session      *discordgo.Session
	voiceConns   map[string]*discordgo.VoiceConnection
	voiceWorkers map[string]*voiceWorker
	audioBuffers map[string]*bytes.Buffer
	httpClient   *http.Client
	mu           sync.Mutex
}

// New は Discord Bot インスタンスを作成します。
func New(opts Options) (*Bot, error) {
	if strings.TrimSpace(opts.Token) == "" {
		return nil, fmt.Errorf("discord token が空です")
	}
	if opts.CommandPrefix == "" {
		opts.CommandPrefix = "!"
	}

	dg, err := discordgo.New("Bot " + strings.TrimSpace(opts.Token))
	if err != nil {
		return nil, fmt.Errorf("discord session 初期化に失敗: %w", err)
	}

	b := &Bot{
		opts:         opts,
		session:      dg,
		voiceConns:   make(map[string]*discordgo.VoiceConnection),
		voiceWorkers: make(map[string]*voiceWorker),
		audioBuffers: make(map[string]*bytes.Buffer),
		httpClient: &http.Client{
			Timeout: 3 * time.Second,
		},
	}
	b.session.AddHandler(b.onMessageCreate)
	// Ready ハンドラを追加して起動時の state 到着をログに記録する
	b.session.AddHandler(func(s *discordgo.Session, r *discordgo.Ready) {
		log.Printf("Discord Ready: user=%s guilds=%d", s.State.User.Username, len(s.State.Guilds))
	})
	// Guilds インテントを追加して、起動時に VoiceStates を含むキャッシュを受け取る
	b.session.Identify.Intents = discordgo.IntentsGuilds | discordgo.IntentsGuildMessages | discordgo.IntentsGuildVoiceStates
	return b, nil
}

// Start は Bot 接続を開始します。
func (b *Bot) Start() error {
	if err := b.session.Open(); err != nil {
		return fmt.Errorf("discord 接続に失敗: %w", err)
	}
	log.Printf("Discord Bot connected: user=%s", b.session.State.User.Username)
	return nil
}

// Close は Bot 接続と Voice 接続を終了します。
func (b *Bot) Close() error {
	b.mu.Lock()
	for guildID, worker := range b.voiceWorkers {
		if worker != nil {
			close(worker.stopCh)
		}
		delete(b.voiceWorkers, guildID)
	}
	for guildID, vc := range b.voiceConns {
		if vc != nil {
			_ = b.disconnectVoiceCompat(vc)
		}
		delete(b.voiceConns, guildID)
	}
	b.mu.Unlock()

	if b.session != nil {
		return b.session.Close()
	}
	return nil
}

func (b *Bot) onMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author == nil || m.Author.Bot {
		return
	}
	if m.GuildID == "" {
		return
	}
	if b.opts.AllowedGuildID != "" && m.GuildID != b.opts.AllowedGuildID {
		return
	}
	if b.opts.AllowedTextChannelID != "" && m.ChannelID != b.opts.AllowedTextChannelID {
		return
	}

	content := strings.TrimSpace(m.Content)
	if !strings.HasPrefix(content, b.opts.CommandPrefix) {
		return
	}

	commandLine := strings.TrimPrefix(content, b.opts.CommandPrefix)
	parts := strings.Fields(commandLine)
	if len(parts) == 0 {
		return
	}

	command := strings.ToLower(parts[0])
	switch command {
	case "ping":
		b.reply(m.ChannelID, "pong")
	case "join":
		b.handleJoin(s, m)
	case "leave":
		b.handleLeave(m)
	case "say":
		if len(parts) < 2 {
			b.reply(m.ChannelID, "使い方: !say テキスト")
			return
		}
		message := strings.Join(parts[1:], " ")
		if b.opts.MinimalPostLength > 0 && len([]rune(strings.TrimSpace(message))) < b.opts.MinimalPostLength {
			b.reply(m.ChannelID, fmt.Sprintf("%d 文字以上で入力してください", b.opts.MinimalPostLength))
			return
		}
		b.reply(m.ChannelID, "[Bot出力テキスト] "+message)
	case "whisper":
		// Whisper テスト: 引数があればそれをプロンプトに使う
		var prompt string
		if len(parts) >= 2 {
			prompt = strings.Join(parts[1:], " ")
		} else {
			prompt = "Whisperテスト"
		}
		// 非同期で生成を呼び出す（メッセージハンドラをブロックしない）
		go func(channelID, sessionID, p string) {
			resp, err := b.sendGenerate(sessionID, p)
			if err != nil {
				b.reply(channelID, "Whisper生成に失敗: "+err.Error())
				return
			}
			resp = strings.TrimSpace(resp)
			if resp == "" {
				b.reply(channelID, "(生成結果なし)")
				return
			}
			b.reply(channelID, "[Whisper] "+resp)
		}(m.ChannelID, m.GuildID, prompt)
	default:
		b.reply(m.ChannelID, "利用可能コマンド: !ping, !join, !leave, !say, !whisper")
	}
}

func (b *Bot) handleJoin(s *discordgo.Session, m *discordgo.MessageCreate) {
	voiceChannelID, err := b.findUserVoiceChannelID(s, m.GuildID, m.Author.ID)
	if err != nil {
		b.reply(m.ChannelID, "ボイスチャンネルに参加してから !join を実行してください")
		return
	}

	if b.opts.AllowedVoiceChannelID != "" && voiceChannelID != b.opts.AllowedVoiceChannelID {
		b.reply(m.ChannelID, "許可されたVC以外には参加できません")
		return
	}

	b.mu.Lock()
	if _, exists := b.voiceConns[m.GuildID]; exists {
		b.mu.Unlock()
		b.reply(m.ChannelID, "既にこのサーバーでVC接続中です")
		return
	}
	b.mu.Unlock()

	// NOTE: 音声受信テストのため selfMute/selfDeaf を両方 false で接続する。
	vc, err := b.channelVoiceJoinCompat(s, m.GuildID, voiceChannelID, false, false)
	if err != nil {
		log.Printf("voice join failed: guild=%s err=%v", m.GuildID, err)
		errText := strings.ToLower(err.Error())
		if strings.Contains(errText, "4017") || strings.Contains(errText, "e2ee") || strings.Contains(errText, "dave") || strings.Contains(errText, "timeout waiting for voice") {
			b.reply(m.ChannelID, "VC参加に失敗しました。サーバー側のE2EE/DAVE設定が有効で、ライブラリ側が未対応の可能性があります。")
		} else {
			b.reply(m.ChannelID, "VCへの参加に失敗しました")
		}
		return
	}

	b.mu.Lock()
	b.voiceConns[m.GuildID] = vc
	worker := &voiceWorker{stopCh: make(chan struct{}), channelID: m.ChannelID}
	b.voiceWorkers[m.GuildID] = worker
	b.mu.Unlock()

	go b.forwardVoicePackets(m.GuildID, worker, vc)

	b.reply(m.ChannelID, "VCに参加しました。音声入力待機を開始します。")
}

func (b *Bot) handleLeave(m *discordgo.MessageCreate) {
	b.mu.Lock()
	vc, exists := b.voiceConns[m.GuildID]
	worker := b.voiceWorkers[m.GuildID]
	if exists {
		delete(b.voiceConns, m.GuildID)
		delete(b.voiceWorkers, m.GuildID)
	}
	b.mu.Unlock()

	if !exists {
		b.reply(m.ChannelID, "現在VC接続はありません")
		return
	}

	if vc != nil {
		_ = b.disconnectVoiceCompat(vc)
	}
	if worker != nil {
		close(worker.stopCh)
	}
	b.reply(m.ChannelID, "VCから退出しました")
}

func (b *Bot) channelVoiceJoinCompat(s *discordgo.Session, guildID, channelID string, mute, deaf bool) (*discordgo.VoiceConnection, error) {
	method := reflect.ValueOf(s).MethodByName("ChannelVoiceJoin")
	if !method.IsValid() {
		return nil, fmt.Errorf("ChannelVoiceJoin メソッドが見つかりません")
	}

	methodType := method.Type()
	if methodType.NumIn() == 5 {
		results := method.Call([]reflect.Value{
			reflect.ValueOf(context.Background()),
			reflect.ValueOf(guildID),
			reflect.ValueOf(channelID),
			reflect.ValueOf(mute),
			reflect.ValueOf(deaf),
		})
		if len(results) != 2 {
			return nil, fmt.Errorf("ChannelVoiceJoin の戻り値が不正です")
		}
		vc, _ := results[0].Interface().(*discordgo.VoiceConnection)
		if err, _ := results[1].Interface().(error); err != nil {
			return nil, err
		}
		if vc == nil {
			return nil, fmt.Errorf("VoiceConnection が nil です")
		}
		return vc, nil
	}

	results := method.Call([]reflect.Value{
		reflect.ValueOf(guildID),
		reflect.ValueOf(channelID),
		reflect.ValueOf(mute),
		reflect.ValueOf(deaf),
	})
	if len(results) != 2 {
		return nil, fmt.Errorf("ChannelVoiceJoin の戻り値が不正です")
	}
	vc, _ := results[0].Interface().(*discordgo.VoiceConnection)
	if err, _ := results[1].Interface().(error); err != nil {
		return nil, err
	}
	if vc == nil {
		return nil, fmt.Errorf("VoiceConnection が nil です")
	}
	return vc, nil
}

func (b *Bot) disconnectVoiceCompat(vc *discordgo.VoiceConnection) error {
	method := reflect.ValueOf(vc).MethodByName("Disconnect")
	if !method.IsValid() {
		return fmt.Errorf("Disconnect メソッドが見つかりません")
	}

	methodType := method.Type()
	if methodType.NumIn() == 1 {
		results := method.Call([]reflect.Value{reflect.ValueOf(context.Background())})
		if len(results) == 1 {
			if err, _ := results[0].Interface().(error); err != nil {
				return err
			}
		}
		return nil
	}

	results := method.Call(nil)
	if len(results) == 1 {
		if err, _ := results[0].Interface().(error); err != nil {
			return err
		}
	}
	return nil
}

func (b *Bot) forwardVoicePackets(guildID string, worker *voiceWorker, vc *discordgo.VoiceConnection) {
	if strings.TrimSpace(b.opts.IngestURL) == "" {
		b.reply(worker.channelID, "Ingest URL が未設定のため音声転送を開始できません")
		return
	}

	silenceMS := b.opts.SilenceMS
	if silenceMS <= 0 {
		silenceMS = 800
	}

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	lastSeen := make(map[string]time.Time)

	for {
		select {
		case <-worker.stopCh:
			for userKey := range lastSeen {
				b.flushFinal(guildID, userKey, worker.channelID)
			}
			return
		case packet := <-vc.OpusRecv:
			if packet == nil || len(packet.Opus) == 0 {
				continue
			}
			userKey := fmt.Sprintf("ssrc-%d", packet.SSRC)
			lastSeen[userKey] = time.Now()
			b.mu.Lock()
			buf := b.audioBuffers[userKey]
			if buf == nil {
				buf = &bytes.Buffer{}
				b.audioBuffers[userKey] = buf
			}
			_, _ = buf.Write(packet.Opus)
			b.mu.Unlock()
		case <-ticker.C:
			now := time.Now()
			for userKey, ts := range lastSeen {
				if now.Sub(ts) >= time.Duration(silenceMS)*time.Millisecond {
					b.flushFinal(guildID, userKey, worker.channelID)
					delete(lastSeen, userKey)
				}
			}
		}
	}
}

func (b *Bot) flushFinal(guildID, userKey, channelID string) {
	b.mu.Lock()
	buf := b.audioBuffers[userKey]
	if buf == nil || buf.Len() == 0 {
		delete(b.audioBuffers, userKey)
		b.mu.Unlock()
		log.Printf("voice final: no buffered audio for guild=%s user=%s", guildID, userKey)
		return
	}
	payload := make([]byte, buf.Len())
	copy(payload, buf.Bytes())
	delete(b.audioBuffers, userKey)
	b.mu.Unlock()

	resp, err := b.sendIngest(guildID, userKey, payload, true)
	if err != nil {
		log.Printf("voice final ingest failed: guild=%s user=%s err=%v", guildID, userKey, err)
		return
	}
	// 詳細ログ
	log.Printf("voice final: guild=%s user=%s partial=%q final=%q bytes=%d chunks=%d elapsed_ms=%d",
		guildID, userKey, resp.PartialText, resp.FinalText, resp.CacheBytes, resp.CacheChunks, resp.ElapsedMs)

	finalText := strings.TrimSpace(resp.FinalText)
	partialText := strings.TrimSpace(resp.PartialText)

	// まず変換後の Whisper をテキストチャットに貼る
	if finalText != "" {
		b.reply(channelID, "[Whisper] "+finalText)
	} else if partialText != "" {
		b.reply(channelID, "[Whisper(部分)] "+partialText)
	} else {
		b.reply(channelID, "[Whisper] (認識結果なし)")
	}

	// 次に生成を試みる（生成に失敗しても Whisper は既に貼られている）
	if finalText != "" {
		answer, err := b.sendGenerate(guildID, finalText)
		if err != nil {
			log.Printf("voice generate failed: guild=%s err=%v", guildID, err)
		} else {
			answer = strings.TrimSpace(answer)
			if answer != "" {
				b.reply(channelID, "[応答] "+answer)
			}
		}
	}
}

func (b *Bot) sendGenerate(sessionID, prompt string) (string, error) {
	endpoint := strings.TrimSpace(b.opts.GenerateURL)
	if endpoint == "" {
		return "", fmt.Errorf("generate url が未設定です")
	}
	model := strings.TrimSpace(b.opts.Model)
	if model == "" {
		model = "live-narrator"
	}

	body, err := json.Marshal(generateRequest{
		Model:     model,
		Prompt:    prompt,
		SessionID: sessionID,
		Parameters: map[string]interface{}{
			"think": false,
		},
	})
	if err != nil {
		return "", err
	}

	req, err := http.NewRequest(http.MethodPost, endpoint, io.NopCloser(bytes.NewReader(body)))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := b.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("generate status %d", resp.StatusCode)
	}

	parsed := &generateResponse{}
	if err := json.Unmarshal(respBody, parsed); err != nil {
		return "", err
	}
	if strings.TrimSpace(parsed.Error) != "" {
		return "", errors.New(parsed.Error)
	}
	return parsed.Response, nil
}

func (b *Bot) sendIngest(sessionID, userID string, payload []byte, final bool) (*ingestResponse, error) {
	u, err := url.Parse(strings.TrimSpace(b.opts.IngestURL))
	if err != nil {
		return nil, err
	}
	q := u.Query()
	q.Set("session_id", sessionID)
	q.Set("user_id", userID)
	q.Set("final", strconv.FormatBool(final))
	u.RawQuery = q.Encode()

	req, err := http.NewRequest(http.MethodPost, u.String(), io.NopCloser(bytes.NewReader(payload)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("X-Audio-Codec", "opus")

	resp, err := b.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("ingest status %d", resp.StatusCode)
	}

	out := &ingestResponse{}
	if err := json.Unmarshal(body, out); err != nil {
		return nil, err
	}

	// 詳細ログ（短めに）
	log.Printf("sendIngest response: session=%s user=%s partial=%q final=%q bytes=%d chunks=%d elapsed_ms=%d",
		sessionID, userID, out.PartialText, out.FinalText, out.CacheBytes, out.CacheChunks, out.ElapsedMs)

	return out, nil
}

func (b *Bot) findUserVoiceChannelID(s *discordgo.Session, guildID, userID string) (string, error) {
	// まず state の直接参照を試す（キャッシュがある場合）
	if vs, verr := s.State.VoiceState(guildID, userID); verr == nil && vs != nil && vs.ChannelID != "" {
		return vs.ChannelID, nil
	}

	// state の guild から VoiceStates を探索
	guild, err := s.State.Guild(guildID)
	if err != nil || guild == nil {
		guild, err = s.Guild(guildID)
		if err != nil {
			// RESTでも見つからない場合、state がまだ到着していない可能性があるため短時間リトライする
			for i := 0; i < 5; i++ {
				time.Sleep(200 * time.Millisecond)
				if vs, verr := s.State.VoiceState(guildID, userID); verr == nil && vs != nil && vs.ChannelID != "" {
					return vs.ChannelID, nil
				}
			}
			return "", fmt.Errorf("voice state not found")
		}
	}

	for _, vs := range guild.VoiceStates {
		if vs.UserID == userID && vs.ChannelID != "" {
			return vs.ChannelID, nil
		}
	}

	// 最終手段で短時間ポーリングして state の到着を待つ
	for i := 0; i < 5; i++ {
		time.Sleep(200 * time.Millisecond)
		if vs, verr := s.State.VoiceState(guildID, userID); verr == nil && vs != nil && vs.ChannelID != "" {
			return vs.ChannelID, nil
		}
	}

	// デバッグ出力
	var lenVS int
	if guild != nil {
		lenVS = len(guild.VoiceStates)
	}
	log.Printf("findUserVoiceChannelID: not found guild=%s user=%s guildVoiceStates=%d", guildID, userID, lenVS)
	return "", fmt.Errorf("voice state not found")
}

func (b *Bot) reply(channelID, message string) {
	if _, err := b.session.ChannelMessageSend(channelID, message); err != nil {
		log.Printf("discord send message failed: %v", err)
	}
}
