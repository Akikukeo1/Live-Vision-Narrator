package config

import "testing"

func TestLoadSettings_EnvOverridesAndDefaults(t *testing.T) {
	t.Setenv("DISCORD_BOT_TOKEN", "secret-token")
	t.Setenv("DISCORD_GUILD_ID", "guild-123")
	t.Setenv("DISCORD_TEXT_CHANNEL_ID", "text-456")
	t.Setenv("DISCORD_VOICE_CHANNEL_ID", "voice-789")
	t.Setenv("SILENCE_MS", "900")
	t.Setenv("CHUNK_MS", "250")
	t.Setenv("MAX_SEGMENT_MS", "12000")
	t.Setenv("MIN_POST_CHARS", "3")
	t.Setenv("POST_COOLDOWN_MS", "1500")
	t.Setenv("STT_ENDPOINT", "http://localhost:9000/v1/transcribe")
	t.Setenv("STT_API_KEY_ENV_NAME", "MY_STT_KEY")

	settings := LoadSettings()

	if settings.DiscordBotToken != "secret-token" {
		t.Fatalf("expected DiscordBotToken from env, got %q", settings.DiscordBotToken)
	}
	if settings.DiscordGuildID != "guild-123" {
		t.Fatalf("expected DiscordGuildID from env, got %q", settings.DiscordGuildID)
	}
	if settings.DiscordTextChannelID != "text-456" {
		t.Fatalf("expected DiscordTextChannelID from env, got %q", settings.DiscordTextChannelID)
	}
	if settings.DiscordVoiceChannelID != "voice-789" {
		t.Fatalf("expected DiscordVoiceChannelID from env, got %q", settings.DiscordVoiceChannelID)
	}
	if settings.SilenceMS != 900 {
		t.Fatalf("expected SilenceMS=900, got %d", settings.SilenceMS)
	}
	if settings.ChunkMS != 250 {
		t.Fatalf("expected ChunkMS=250, got %d", settings.ChunkMS)
	}
	if settings.MaxSegmentMS != 12000 {
		t.Fatalf("expected MaxSegmentMS=12000, got %d", settings.MaxSegmentMS)
	}
	if settings.MinPostChars != 3 {
		t.Fatalf("expected MinPostChars=3, got %d", settings.MinPostChars)
	}
	if settings.PostCooldownMS != 1500 {
		t.Fatalf("expected PostCooldownMS=1500, got %d", settings.PostCooldownMS)
	}
	if settings.STTEndpoint != "http://localhost:9000/v1/transcribe" {
		t.Fatalf("expected STTEndpoint from env, got %q", settings.STTEndpoint)
	}
	if settings.STTAPIKeyEnvName != "MY_STT_KEY" {
		t.Fatalf("expected STTAPIKeyEnvName from env, got %q", settings.STTAPIKeyEnvName)
	}
}

func TestLoadSettings_DiscordLegacyChannelFallback(t *testing.T) {
	t.Setenv("DISCORD_CHANNEL_ID", "legacy-channel")

	settings := LoadSettings()

	if settings.DiscordTextChannelID != "legacy-channel" {
		t.Fatalf("expected DiscordTextChannelID fallback, got %q", settings.DiscordTextChannelID)
	}
	if settings.DiscordVoiceChannelID != "legacy-channel" {
		t.Fatalf("expected DiscordVoiceChannelID fallback, got %q", settings.DiscordVoiceChannelID)
	}
}

func TestSettings_RequireDiscordToken(t *testing.T) {
	if err := (&Settings{}).RequireDiscordToken(); err == nil {
		t.Fatal("expected error when Discord token is missing")
	}
	if err := (&Settings{DiscordBotToken: "ok"}).RequireDiscordToken(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestSettings_ResolveSTTAPIKey(t *testing.T) {
	t.Setenv("STT_API_KEY", "api-key-123")

	settings := &Settings{STTAPIKeyEnvName: "STT_API_KEY"}
	value, err := settings.ResolveSTTAPIKey()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if value != "api-key-123" {
		t.Fatalf("expected api-key-123, got %q", value)
	}

	settings.STTAPIKeyEnvName = "MISSING_STT_KEY"
	if _, err := settings.ResolveSTTAPIKey(); err == nil {
		t.Fatal("expected error for missing env value")
	}
}
