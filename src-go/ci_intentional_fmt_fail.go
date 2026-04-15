package main

// このファイルは複数種類の linter トラップを意図的に含みます。
// - gofumpt によるフォーマット違反（インデント崩し）
// - unused による未使用グローバル
// - errcheck によるエラー無視
// - ineffassign による不要な代入
// - govet (printf のフォーマット不一致)
// FIXME: テスト後に削除してください。

import "fmt"

// フォーマット違反を起こす（故意のインデント崩し）
func fmtFail() {
fmt.Println("This file intentionally fails gofumpt formatting check")
}

// 未使用のグローバル（`unused` リンターが検出）
var UnusedGlobal = 42

// errcheck を誘発: エラー戻り値をチェックせず無視する呼び出し
func ignoreErr() {
	fmt.Println("ignoring error from Println")
}

// ineffassign を誘発: 初期代入値が上書きされる（最初の代入が無駄）
func ineffAssign() {
	x := 1
	x = 2
	_ = x
}

// govet の printf 検査を誘発（型が合わない）
func vetPrintf() {
	fmt.Printf("%d", "not a number")
}

// コンパイルのために参照を残す（lint のみを引き起こす）
var _ = fmtFail
var _ = ignoreErr
var _ = ineffAssign
var _ = vetPrintf
