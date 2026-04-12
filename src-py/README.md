# src-py

現在、このAPIはPythonからGoへ移行しています。Pythonは廃止されます。src-goが新しいコードベースで、src-pyは古いコードベースです。src-pyは移行期間中に参照用として残されますが、新しい機能はsrc-goに追加されます。src-pyのコードは将来的に削除される予定です。

## 移行状況

client_test.py: 現在、現役のデバッガ用のテストコードです。これがCIで実行される事はありません。
config.py: 完了 → config.go に移行
main.py: 完了 → main.go, text_processor.go, ollama_client.go に移行
ui.py: 現在、UIコードをPython+HTML,CSS,JavaScriptに移行中です。UI分野では、パフォーマンスを向上する必要がありません。（UIで重い処理をしようとする人はいない…）そのため、UIコードはPythonで残すことを検討しています。将来的には、UIコード何らかのフロントエンドフレームワーク（React, Vue, Svelteなど）に移行することも検討していますが、当面はPythonでUIコードを維持する予定です。
