package config

import (
	"fmt"
	"os"
	"strconv"

	"github.com/BurntSushi/toml"
	_ "github.com/joho/godotenv/autoload"
)

// Settings はアプリケーションの設定を保持します
type Settings struct {
	// Ollama connection
	OllamaURL          string `toml:"ollama_url"`
	OllamaGeneratePath string `toml:"ollama_generate_path"`
	OllamaModelsPath   string `toml:"ollama_models_path"`
	DefaultThink       bool   `toml:"default_think"`
	DefaultModel       string `toml:"default_model"`

	// Logging
	LogLevel string `toml:"log_level"`

	// Server ports
	HostIP  string `toml:"host_ip"`
	UIIP    string `toml:"ui_ip"`
	APIHost string `toml:"api_host"`
	APIPort int    `toml:"api_port"`
	UIPort  int    `toml:"ui_port"`

	// System profile file paths
	SystemDefaultFile  string `toml:"system_default_file"`
	SystemDetailedFile string `toml:"system_detailed_file"`

	// Session management
	ModelIdleSeconds int `toml:"model_idle_seconds"`
	MaxContextTokens int `toml:"max_context_tokens"`

	// Discord / STT
	DiscordBotToken          string `toml:"-"`
	DiscordGuildID           string `toml:"discord_guild_id"`
	DiscordTextChannelID     string `toml:"discord_text_channel_id"`
	DiscordVoiceChannelID    string `toml:"discord_voice_channel_id"`
	LegacyDiscordChannelID   string `toml:"discord_channel_id"`
	SilenceMS                int    `toml:"silence_ms"`
	ChunkMS                  int    `toml:"chunk_ms"`
	MaxSegmentMS             int    `toml:"max_segment_ms"`
	MinPostChars             int    `toml:"min_post_chars"`
	PostCooldownMS           int    `toml:"post_cooldown_ms"`
	STTEndpoint              string `toml:"stt_endpoint"`
	STTAPIKeyEnvName         string `toml:"stt_api_key_env_name"`
}

// LoadSettings は config.toml から設定を読み込み、環境変数で上書きします
func LoadSettings() *Settings {
	s := &Settings{
		// Defaults
		OllamaURL:          "http://localhost:11434",
		OllamaGeneratePath: "/api/generate",
		OllamaModelsPath:   "/api/tags",
		DefaultThink:       false,
		DefaultModel:       "live-narrator",
		LogLevel:           "INFO",
		HostIP:             "0.0.0.0",
		UIIP:               "0.0.0.0",
		APIHost:            "localhost",
		APIPort:            8000,
		UIPort:             8001,
		SystemDefaultFile:  "Modelfile",
		SystemDetailedFile: "Modelfile.detailed",
		ModelIdleSeconds:   2000,
		MaxContextTokens:   0,
		SilenceMS:          800,
		ChunkMS:            200,
		MaxSegmentMS:       15000,
		MinPostChars:       1,
		PostCooldownMS:     1000,
		STTAPIKeyEnvName:   "STT_API_KEY",
	}

	// config.toml からの読み込みを試みる
	// NOTE: デフォルトの ModelIdleSeconds=2000 は長めに設定されています。
	configPath := "config.toml"
	if data, err := os.ReadFile(configPath); err == nil {
		if err := toml.Unmarshal(data, s); err != nil {
			_ = err
		}
	}

	// 環境変数による上書き
	if v := os.Getenv("OLLAMA_URL"); v != "" {
		s.OllamaURL = v
	}
	if v := os.Getenv("LOG_LEVEL"); v != "" {
		s.LogLevel = v
	}
	if v := os.Getenv("DISCORD_BOT_TOKEN"); v != "" {
		s.DiscordBotToken = v
	}
	if v := os.Getenv("DISCORD_GUILD_ID"); v != "" {
		s.DiscordGuildID = v
	}
	if v := os.Getenv("DISCORD_TEXT_CHANNEL_ID"); v != "" {
		s.DiscordTextChannelID = v
	}
	if v := os.Getenv("DISCORD_VOICE_CHANNEL_ID"); v != "" {
		s.DiscordVoiceChannelID = v
	}
	if v := os.Getenv("DISCORD_CHANNEL_ID"); v != "" {
		s.LegacyDiscordChannelID = v
	}

	// 旧設定 DISCORD_CHANNEL_ID / discord_channel_id からのフォールバック。
	if s.DiscordTextChannelID == "" {
		s.DiscordTextChannelID = s.LegacyDiscordChannelID
	}
	if s.DiscordVoiceChannelID == "" {
		s.DiscordVoiceChannelID = s.LegacyDiscordChannelID
	}
	if v := os.Getenv("SILENCE_MS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed >= 0 {
			s.SilenceMS = parsed
		}
	}
	if v := os.Getenv("CHUNK_MS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed > 0 {
			s.ChunkMS = parsed
		}
	}
	if v := os.Getenv("MAX_SEGMENT_MS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed > 0 {
			s.MaxSegmentMS = parsed
		}
	}
	if v := os.Getenv("MIN_POST_CHARS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed >= 0 {
			s.MinPostChars = parsed
		}
	}
	if v := os.Getenv("POST_COOLDOWN_MS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed >= 0 {
			s.PostCooldownMS = parsed
		}
	}
	if v := os.Getenv("STT_ENDPOINT"); v != "" {
		s.STTEndpoint = v
	}
	if v := os.Getenv("STT_API_KEY_ENV_NAME"); v != "" {
		s.STTAPIKeyEnvName = v
	}

	return s
}

// RequireDiscordToken は Discord Bot の起動条件を検証します。
func (s *Settings) RequireDiscordToken() error {
	if s == nil || s.DiscordBotToken == "" {
		return fmt.Errorf("Discord Bot トークンが設定されていません")
	}
	return nil
}

// ResolveSTTAPIKey は設定された環境変数名から STT 用 API キーを取得します。
func (s *Settings) ResolveSTTAPIKey() (string, error) {
	if s == nil {
		return "", fmt.Errorf("設定が初期化されていません")
	}
	envName := s.STTAPIKeyEnvName
	if envName == "" {
		envName = "STT_API_KEY"
	}
	value := os.Getenv(envName)
	if value == "" {
		return "", fmt.Errorf("STT API キーが環境変数 %s に設定されていません", envName)
	}
	return value, nil
}

// GetSystemProfilePath はシステムプロファイルファイルへのパスを返します
func (s *Settings) GetSystemProfilePath(name string) string {
	switch name {
	case "default":
		return s.SystemDefaultFile
	case "detailed":
		return s.SystemDetailedFile
	default:
		return ""
	}
}

// ReadSystemProfile は指定された名前のシステムプロファイルファイルを読み込みます（許可された名前のみ）
func (s *Settings) ReadSystemProfile(name string) (string, error) {
	path := s.GetSystemProfilePath(name)
	if path == "" {
		return "", nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(data), nil
}
