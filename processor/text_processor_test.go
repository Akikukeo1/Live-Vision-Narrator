package processor

import (
	"testing"
)

func TestSanitizeResponse(t *testing.T) {
	tp := NewTextProcessor()

	// Test without think tags
	input := "Hello world"
	result := tp.SanitizeResponse(input, false)
	if result != "Hello world" {
		t.Errorf("Expected 'Hello world', got '%s'", result)
	}

	// Test with think tags (should be removed)
	inputWithThink := "Before <think>internal thought</think> After"
	result = tp.SanitizeResponse(inputWithThink, false)
	if result != "Before  After" {
		t.Errorf("Expected 'Before  After', got '%s'", result)
	}

	// Test with reveal_thoughts=true (should keep tags)
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

	// Test without inner_voice
	noVoice := "Just some text"
	result = tp.ExtractInnerVoice(noVoice)
	if result != "" {
		t.Errorf("Expected empty string, got '%s'", result)
	}
}
