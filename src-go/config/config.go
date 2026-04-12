package config

import (
	"os"

	"github.com/BurntSushi/toml"
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

	return s
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
