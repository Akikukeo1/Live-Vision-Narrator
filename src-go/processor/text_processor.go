package processor

import (
	"regexp"
	"strings"
)

// Pre-compiled regexes for performance
var (
	thinkTagRegex      = regexp.MustCompile(`(?i)<think>.*?</think>`)
	innerVoiceTagRegex = regexp.MustCompile(`(?i)<inner_voice>([\s\S]*?)</inner_voice>`)
)

// TextProcessor handles text sanitization and formatting
type TextProcessor struct {
}

// NewTextProcessor creates a new text processor
func NewTextProcessor() *TextProcessor {
	return &TextProcessor{}
}

// SanitizeResponse removes think tags and returns clean text
func (tp *TextProcessor) SanitizeResponse(text string, revealThoughts bool) string {
	if revealThoughts {
		// Keep response intact if revealing thoughts
		return text
	}

	// Remove think tags
	cleaned := thinkTagRegex.ReplaceAllString(text, "")
	return strings.TrimSpace(cleaned)
}

// ExtractInnerVoice extracts inner_voice content from response
func (tp *TextProcessor) ExtractInnerVoice(text string) string {
	matches := innerVoiceTagRegex.FindStringSubmatch(text)
	if len(matches) > 1 {
		return strings.TrimSpace(matches[1])
	}
	return ""
}

// RemoveThinkTags removes all think tags from text
func (tp *TextProcessor) RemoveThinkTags(text string) string {
	return thinkTagRegex.ReplaceAllString(text, "")
}

// CleanJSON ensures JSON output is properly formatted
func (tp *TextProcessor) CleanJSON(data map[string]interface{}, revealThoughts bool) {
	if !revealThoughts {
		delete(data, "thinking")
	}

	// Optionally remove or process response
	if resp, ok := data["response"].(string); ok {
		data["response"] = tp.SanitizeResponse(resp, revealThoughts)
	}
}
