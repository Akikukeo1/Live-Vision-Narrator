package main

// このファイルは意図的にフォーマットを崩してあります。
// `gofumpt -l -e src-go` のフォーマットチェック用トラップです。
// FIXME: CI テストが完了したらファイルを削除してください。
// TODO: CI テストが完了したらファイルを削除してください。
import "fmt"

func fmtFail() {
fmt.Println("This file intentionally fails gofumpt formatting check")
}

func fmtFail() {
fmt.Println("This file intentionally fails gofumpt formatting check")
}

// 未使用エラーで CI が失敗しないように参照を保持します。
var _ = fmtFail
