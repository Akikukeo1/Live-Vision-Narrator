package main

import "fmt"

// LintFail は未使用の変数を含むため、golangci-lint によって警告されます。
// FIXME: CIテストが完了したらこのファイルを削除してください。
// TODO: CIテストが完了したらこのファイルを削除してください。
func LintFail() {
	var unusedVar int
	fmt.Println("This file intentionally triggers a linter warning: unused variable")
	_ = unusedVar // 一時的にコメントアウトすると検出されなくなるため、故意に未使用とする
}
