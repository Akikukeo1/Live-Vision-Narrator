package processor

import (
	"regexp"
	"strings"
)

// パフォーマンスのため事前コンパイルした正規表現
var (
	thinkTagRegex      = regexp.MustCompile(`(?is)<think>.*?</think>`)
	innerVoiceTagRegex = regexp.MustCompile(`(?i)<inner_voice>([\s\S]*?)</inner_voice>`)
)

// TextProcessor はテキストのサニタイズやフォーマットを処理します
type TextProcessor struct {
}

// NewTextProcessor は新しいテキストプロセッサを作成します
func NewTextProcessor() *TextProcessor {
	return &TextProcessor{}
}

// SanitizeResponse は <think> タグを削除し、クリーンなテキストを返します
func (tp *TextProcessor) SanitizeResponse(text string, revealThoughts bool) string {
	if revealThoughts {
		// 思考を明示する場合はテキストをそのまま返す
		return text
	}

	// <think> タグを削除
	cleaned := thinkTagRegex.ReplaceAllString(text, "")
	return strings.TrimSpace(cleaned)
}

// ExtractInnerVoice は <inner_voice> タグ内の内容を抽出します
func (tp *TextProcessor) ExtractInnerVoice(text string) string {
	matches := innerVoiceTagRegex.FindStringSubmatch(text)
	if len(matches) > 1 {
		return strings.TrimSpace(matches[1])
	}
	return ""
}

// RemoveThinkTags はテキストからすべての <think> タグを削除します
func (tp *TextProcessor) RemoveThinkTags(text string) string {
	return thinkTagRegex.ReplaceAllString(text, "")
}

// CleanJSON は JSON 出力が正しくフォーマットされるようにします
// NOTE: この処理は出力の書式を保つための軽微な整形のみを行います。
// NOTE: JSON スキーマに応じた厳密な検証やエスケープ処理が必要な場合、ここで実装してください。
func (tp *TextProcessor) CleanJSON(data map[string]interface{}, revealThoughts bool) {
	if !revealThoughts {
		delete(data, "thinking")
	}

	// 必要に応じて response を処理
	if resp, ok := data["response"].(string); ok {
		data["response"] = tp.SanitizeResponse(resp, revealThoughts)
	}
}
