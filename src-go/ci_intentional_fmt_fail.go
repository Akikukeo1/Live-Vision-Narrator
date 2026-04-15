package main

// このファイルは意図的にフォーマットを崩してあります。
// `gofumpt -l -e src-go` のフォーマットチェック用トラップです。
// FIXME: CI テストが完了したらファイルを削除してください。
// TODO: CI テストが完了したらファイルを削除してください。
import "fmt"

// 故意に一行で記述して gofumpt が差分として検出するようにしています。
func fmtFail() { fmt.Println("This file intentionally fails gofumpt formatting check") }

// 未使用エラーで CI が失敗しないように参照を保持します。
var _ = fmtFail
