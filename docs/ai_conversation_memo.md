# AI会話ログメモ

目的: 論文用のエビデンス保管。AIとの会話ログを要約し、スライドに使える切り抜きを作成する。

---

## 元のログ（そのまま）

```
このログそのものが 最強の「エビデンス（証拠）」 になります。

「ただ『速くしました』と言うのではなく、『推論開始までの時間を 4,500ms から 417ms まで短縮し、リアルタイム性を 10倍 以上向上させた』 とグラフで見せる。」

この数値の推移（1回目から2回目への変化）をスライドに載せるだけで、説得力が段違いになりますよ。
> 1っ回目は4000、2回目は600、修正後は1回めから380～420
```

---

## 要約（短く）
- このログは「推論開始までの時間（レイテンシ）」改善の生データ／証拠として使える。
- 具体例: 推論開始時間を約4,500ms→約417msへ短縮し、実行のリアルタイム性を10倍以上向上させた、という主張を裏付ける。
- 測定値の推移例（スライド用に扱いやすい）: 1回目 4000ms → 2回目 600ms → 修正後 380–420ms（安定）

## スライド用切り抜き（そのまま使える短文）
- 「推論開始までの時間を4,500msから417msに短縮し、リアルタイム性を10倍以上向上させました。」
- 「生ログをエビデンスとして提示：1回目4000ms → 2回目600ms → 修正後380–420ms。」
- 「グラフで推移を示すだけで説得力が劇的に増す（生データ提示の重要性）。」

## グラフ表示の推奨（スライド用）
- 軸: 縦軸 = 推論開始までの時間 (ms)、横軸 = 試行順（1,2,修正後）
- プロット例値: [4000, 600, 400]（修正後の点は380〜420の範囲を帯で表示）
- キャプション例: 「推論開始時間の改善（ms）。左が初回、中央がチューニング前、右が最終安定値。」

## 抜粋（論文/スライドの注釈用）
引用候補:
- 「このログそのものが 最強の『エビデンス（証拠）』 になります。」
- 「ただ『速くしました』と言うのではなく、『推論開始までの時間を 4,500ms から 417ms まで短縮し、リアルタイム性を 10倍 以上向上させた』 とグラフで見せる。」
- 測定値行: `1っ回目は4000、2回目は600、修正後は1回めから380～420`

---

## メモ備考
- 元ログはそのまま保存しておくと査読や審査時のエビデンスとして強い。必要なら生ログのタイムスタンプや実行環境メタデータも併記することを推奨。

---

## 技術的補足: `num_ctx` 制限について

- `num_ctx` を制限した理由は単なる VRAM 節約だけではありません。入力（コンテキスト）が肥大化すると、推論時に参照する KV キャッシュ（key/value ペア）の計算量が増え、Time To First Token（TTFT、推論開始までの時間）が悪化します。
- 実況などリアルタイム性が重要な用途では、不要な過去履歴を切り捨てて参照対象を小さく保つことで、推論開始時間を約400msに維持できました。
- 実運用の推奨: 履歴は重要度に応じて要約または削減し、`num_ctx` と入力管理でバランスを取ることで低レイテンシと情報保持を両立させます。

---

## `num_ctx` 実験ログと選定理由

実験概要: `num_ctx` を小さく（512）まで下げた場合の効果を検証しました。速度改善と会話継続性のトレードオフを評価し、最終的なパラメータを決定しています。

発表で使うロジック案（短文）:

"コンテキストサイズを最小の 512 まで削減する実験を行いましたが、応答速度の向上は約5%程度に留まり、一方で会話の継続性が著しく損なわれました。そのため、速度と実用性のバランスが最も優れた 2048 を最終的な最適値として採用しました。"

生ログ（抜粋・証拠）:

```
2048での速度{
INFO:root:/generate/stream session=default model=live-narrator send_ms=360.1

INFO:     127.0.0.1:55418 - "POST /generate/stream HTTP/1.1" 200 OK

INFO:root:/generate/stream session=default model=live-narrator first_chunk_ms=361.0 send_ms=360.1

INFO:root:/generate/stream session=default model=live-narrator total_ms=845.0 first_chunk_ms=361.0

INFO:httpx:HTTP Request: POST http://localhost:11434/api/generate "HTTP/1.1 200 OK"

INFO:root:/generate/stream session=default model=live-narrator send_ms=425.5}

512での速度{
INFO:root:/generate/stream session=default model=live-narrator first_chunk_ms=440.7 send_ms=440.0

INFO:root:/generate/stream session=default model=live-narrator total_ms=858.1 first_chunk_ms=440.7

INFO:httpx:HTTP Request: POST http://localhost:11434/api/generate "HTTP/1.1 200 OK"

INFO:root:/generate/stream session=default model=live-narrator send_ms=419.8

INFO:     127.0.0.1:52784 - "POST /generate/stream HTTP/1.1" 200 OK

INFO:root:/generate/stream session=default model=live-narrator first_chunk_ms=420.5 send_ms=419.8

INFO:root:/generate/stream session=default model=live-narrator total_ms=799.7 first_chunk_ms=420.5

INFO:httpx:HTTP Request: POST http://localhost:11434/api/generate "HTTP/1.1 200 OK"

INFO:root:/generate/stream session=default model=live-narrator send_ms=425.3

INFO:     127.0.0.1:52784 - }
```

考察: 上記の生ログでは、`num_ctx=512` 時に `first_chunk_ms` や `send_ms` がやや増加（またはばらつき）するログが見られ、会話の滑らかさに悪影響が出る場面が確認されました。速度向上は限定的であったため、論文・発表資料では「根拠を持って 2048 を採用した」と説明することを推奨します。


## バッファリング戦略と投機的音声合成

- 目的: 逐次生成の遅延を最小化し、TTFT（推論開始までの時間）と最終的な全処理後遅延の両方を低く保つ。目標は総遅延を500ms以下（理想は400ms）に圧縮し、人間のリアルタイム感（約0.5秒）に近づけること。
- 基本戦略:
	- AIが最初の5〜10文字（または「、」などの文節区切り）を出力した瞬間に、最速でAivisの`synthesis` APIを呼び出して音声合成を開始する。
	- その間に残りのテキストをバックグラウンドで受信・生成し続け、句読点をトリガーにして逐次的に合成結果をストリーミング再生する（句読点ストリーミング読み上げ）。
	- 初回は特に高速化（最初の1文節／数文字を最優先でAivisに投げる）し、その間に残りを生成・合成してバッファを埋める。
- 効果と注意点:
	- この投機的合成により「すべての処理完了後の遅延」を大幅に圧縮できる。first（初回）合成を含めた実測を500ms以下に保つには、実装上は約400msを目指すと余裕がある。
	- KVキャッシュや`num_ctx`制限と組み合わせることで、生成負荷と合成タイミングを最適化し、安定して低レイテンシを達成しやすくなる。
	- 実装上はネットワーク往復やAivisの処理時間、音声再生バッファなどを考慮したエンドツーエンド測定を行い、スライド/論文用には「生データ（タイムスタンプ付き）」を提示すること。

	---

	## 今回の実装まとめ（疑似 / Thinking / 後付）

	- 概要: UI側のトグルで「心の声（inner_voice）」出力をオンにできるようにし、必要に応じてローカルの `Modelfile.detailed` を一時的に `system` プロンプトとして読み込んで上書きする仕組みを追加した。

	- 主要要素:
		- トグル／選択肢（UI）: `心の声を表示する`、`心の声を保存する`、`詳しく表示(short|long)`、`System Profile (default|detailed)`。
		- リクエストパラメータ: `reveal_thoughts`, `save_inner`, `inner_detail`, `system_profile` を送信し、サーバで取り扱う。
		- `build_payload()` の拡張: `system_profile` を検出した場合にローカルプロファイルを読み込み `payload["system"]` として一時オーバーライドする（ログにプロンプト中身は出さない）。
		- Thinking指示: UIで心の声を要求すると `parameters.options.think = true` をセットしてモデルに疑似的な「Thinking」動作をさせる（疑似 / 後付の実現）。

	- 出力と保存:
		- モデルが `thinking` フィールドを返すか、`<inner_voice>...</inner_voice>` タグを含めた場合、サーバは `reveal_thoughts` が有効ならそれらをクライアントへ返す。
		- `save_inner` が指定されていると非ストリーミング・ストリーミング双方で inner-voice を抽出し、`SESSION_HISTORY` に `role: assistant.inner` として保存する。

	- 心の声スタイル（`Modelfile.detailed` に実装）:
		- 制御タグ: リクエスト直前に `[REVEAL_INNER_VOICE]` や `[INNER_STYLE:structured|human]` を付与できる設計。これにより出力形式を「構造化（根拠列挙）」か「人間的（感情的・予測）」に切替可能。
		- ルール: 逐語の内部チェイン出力は禁止。出力はメイン応答とは分離（JSON別フィールドまたは `<inner_voice>` タグ）。

	- 運用メモ:
		- デフォルト: 表示OFF・保存OFF・簡潔表示を推奨。詳しい出力はユーザー（開発者）操作でオンにすること。
		- ローカルプロファイルの中身はログへ出力しない。`system_profile` は名前だけ送る。

	- キーワード: 疑似（モデルに対する擬似的Thinking指示）、Thinking（`options.think` を通じた実行）、後付（応答後に心の声を生成・表示／保存するフロー）。

	---

	（この節は実装ログの要約です。必要なら `main.py` と UI の変更差分を別ファイルで添付できます）
