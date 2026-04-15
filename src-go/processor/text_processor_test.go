package processor

import (
	"testing"
)

func TestSanitizeResponse(t *testing.T) {
	tp := NewTextProcessor()

	// think タグなしのテスト
	input := "Hello world"
	result := tp.SanitizeResponse(input, false)
	if result != "Hello world" {
		t.Errorf("Expected 'Hello world', got '%s'", result)
	}

	// think タグありのテスト（削除されること）
	inputWithThink := "Before <think>internal thought</think> After"
	result = tp.SanitizeResponse(inputWithThink, false)
	if result != "Before  After" {
		t.Errorf("Expected 'Before  After', got '%s'", result)
	}

	// reveal_thoughts=true の場合はタグを保持するテスト
	result = tp.SanitizeResponse(inputWithThink, true)
	if result != inputWithThink {
		t.Errorf("Expected original text when revealing thoughts, got '%s'", result)
	}
}

func TestExtractInnerVoice(t *testing.T) {
	tp := NewTextProcessor()

	input := "Response text <inner_voice>My inner thoughts</inner_voice> more text"
	result := tp.ExtractInnerVoice(input)
	if result != "My inner thoughts" {
		t.Errorf("Expected 'My inner thoughts', got '%s'", result)
	}

	// inner_voice タグなしのテスト
	noVoice := "Just some text"
	result = tp.ExtractInnerVoice(noVoice)
	if result != "" {
		t.Errorf("Expected empty string, got '%s'", result)
	}
}
