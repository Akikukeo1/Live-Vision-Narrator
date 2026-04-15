package main

// このファイルは意図的にフォーマットを崩してあり、
// `gofumpt -l -e src-go` などのフォーマットチェックで検出されます。
// FIXME: CIテストが完了したらこのファイルを削除してください。
// TODO: CIテストが完了したらこのファイルを削除してください。
import "fmt"

func          fmtFail(

) {
	fmt.Println( "This file intentionally fails gofumpt formatting check " )
}
