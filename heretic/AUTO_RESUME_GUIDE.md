# Heretic Colab 自動再開ガイド（pexpect）

このドキュメントは、Google Colab 上で Heretic を実行する際に、ランタイム復帰後に自動的にチェックポイントから再開する機能の使用方法を説明します。

## 概要

Colab のランタイムが予告なく切断された場合、以下の仕組みで自動的に復帰できます：

1. **Drive マウント**：Google Drive に Heretic のチェックポイントを保存
2. **バックグラウンド同期**：実行中に 60 秒ごとに自動同期（ランタイム切断対策）
3. **自動再開（pexpect）**：Heretic の対話プロンプト「Continue / Restart」に自動で「Continue」を送信

## セットアップ手順

### 1. Google Drive マウント（既存セル）

`colab_setup.ipynb` の「Optional: Mount Google Drive」セルで `MOUNT_DRIVE = True` を設定：

```python
MOUNT_DRIVE = True  #@param {type:"boolean"}
```

### 2. pexpect インストール（新セル）

「Install pexpect for auto-response」セルを実行：

```python
!pip install pexpect -q
print('✓ pexpect installed successfully')
```

### 3. 復元・同期の開始（既存セル）

「Restore from Drive & Start Background Sync」セルを実行（pexpect インストールの直後）。このセルは：
- Drive からローカルにチェックポイント復元
- バックグラウンドスレッドで 60 秒ごとに同期開始

### 4. Heretic 実行（修正済みセル）

「Run Heretic (Auto-Resume with pexpect)」セルを実行。以下のパラメータが利用可能：

| パラメータ | 型 | デフォルト | 説明 |
| :--- | :--- | :--- | :--- |
| `AUTO_RESUME` | bool | True | 自動再開を有効にする |
| `AUTO_RESUME_TIMEOUT` | int | 300 | プロンプト待機のタイムアウト（秒） |
| `use_quantization` | bool | True | 量子化を使用する（bnb_4bit） |
| `skip_batch_autodetect` | bool | True | バッチサイズ自動検出をスキップ |
| `fixed_batch_size` | int | 128 | 固定バッチサイズ |

## 動作フロー

```
ノートブック起動
    ↓
Mount Google Drive
    ↓
Clone / Install heretic
    ↓
Download model
    ↓
Install pexpect
    ↓
Restore from Drive & Start Background Sync
    ├─ Drive から /content/checkpoints に復元
    └─ バックグラウンドスレッド開始
    ↓
Run Heretic (Auto-Resume with pexpect)
    ├─ heretic プロセス起動
    ├─ 「How would you like to proceed?」プロンプト待機
    ├─ 「1」（Continue）を自動送信 ← pexpect の自動化
    ├─ 学習再開
    └─ ログを heretic_run.log に記録
    ↓
Final sync to Drive
    ├─ /content/checkpoints → Drive に同期
    └─ セッション終了
```

## 自動再開の動作モード

### モード 1: 新規実行（チェックポイントなし）

- Heretic は新規の Optuna Study を作成
- pexpect は「Continue」プロンプトを検出しない（タイムアウト）
- フォールバック：通常の subprocess 実行に切り替わり、ユーザー入力を待つ
- **結果**：初回実行と同じ動作

### モード 2: 復帰実行（チェックポイントあり、未完了）

- Heretic は既存の Study を検出
- 「You have already processed this model, but the run was interrupted...」が表示
- 「How would you like to proceed?」プロンプトに pexpect が反応
- 「1」（Continue）を自動送信
- **結果**：ユーザー操作なしで前回の中断地点から再開

### モード 3: 完了済み実行（チェックポイントあり、完了）

- Heretic は既存の Study を検出
- 「You have already processed this model.」が表示
- 「How would you like to proceed?」プロンプトに pexpect が反応
- 「1」（Show the results）を自動送信
- **結果**：前回の結果を表示（追加試行なし）

## テスト手順

### テスト 1: 新規実行（チェックポイントなし）

1. Drive に `/content/drive/MyDrive/heretic/checkpoints` が**空**であることを確認
2. ノートブルを全セル実行（ただし「Run Heretic」セルは途中（20 試行程度）で Ctrl+C で中断）
3. **期待動作**：Heretic が新規 Study を作成し、バックグラウンド同期が開始

### テスト 2: 中断→再開（pexpect 検証）

1. テスト 1 で中断したチェックポイント（`--content--models--google--gemma-4-E4B-it.jsonl`）が Drive に同期されていることを確認
2. `AUTO_RESUME = True` を確認
3. 再度「Run Heretic」セルを実行
4. **期待動作**：
   - ログに `[auto-resume] Detected continuation prompt, sending '1' (Continue)...` が表示
   - `Resuming existing study.` メッセージが出力
   - 前回中断した地点から試行が再開
   - `heretic_run.log` に中断→再開の全ログが記録

### テスト 3: タイムアウト/フォールバック

1. Drive から `/content/checkpoints` を削除（または空にする）
2. `AUTO_RESUME_TIMEOUT` を短く設定（例：10 秒）
3. 「Run Heretic」セルを実行
4. **期待動作**：
   - `[auto-resume] Timeout waiting for prompt` が表示
   - フォールバックして通常の subprocess 実行に切り替わり
   - ユーザーは新規 Study として 0 から開始（またはマニュアルで Continue/Restart 選択）

### テスト 4: ランタイム切断シミュレーション

1. テスト 2 の状態で再度「Run Heretic」セルを実行中に**ランタイムを停止**（セッション中止）
2. ノートブックを再度開く
3. **Drive からのチェックポイント復元から始まる**ノートブック操作を行う（全セル再実行）
4. **期待動作**：
   - 復元セルで最新のチェックポイントが `/content/checkpoints` に復元
   - 「Run Heretic」セルで pexpect が「Continue」を自動送信
   - 同期スレッドが起動し、新しい試行結果が Drive に定期同期

## ログ確認

`heretic_run.log` を確認して実行状況を確認できます：

```bash
# ノートブック内で実行
!tail -100 /content/Live-Vision-Narrator/heretic/heretic_run.log
```

または Drive 側：

```bash
# Drive 同期後、ローカルマシンで確認
gs://My\ Drive/heretic/heretic_run.log  # GDrive path
```

## トラブルシューティング

### Q: `pexpect` がインストールされていないエラー

**A**: 「Install pexpect for auto-response」セルを実行してください。

### Q: `[auto-resume error]` が表示されて自動再開が失敗

**A**: 以下を確認：
1. `pexpect.spawn()` の正規表現が Heretic の出力と一致しているか（ログで `How would you like to proceed?` を検索）
2. `AUTO_RESUME_TIMEOUT` が十分に長いか（デフォルト 300 秒）
3. `--study-checkpoint-dir` が正しく設定されているか

**フォールバック**：失敗時は自動的に `subprocess.run` に切り替わるため、マニュアル操作で「Continue」を選択できます。

### Q: ランタイム切断後、Drive の最新チェックポイントが復元されない

**A**: 以下を確認：
1. 「Restore from Drive & Start Background Sync」セルが実行されたか
2. `MOUNT_DRIVE = True` が設定されているか
3. バックグラウンド同期スレッドが動作中か（「Starting background sync thread」ログ確認）
4. Drive の `/content/drive/MyDrive/heretic/checkpoints` に `.jsonl` ファイルがあるか

### Q: 同期中の `.jsonl` ファイル破損を防ぐには

**A**: `rsync` の `--inplace` / `--partial` オプションを使用するか、一時ファイルへ同期後に原子的にリネームする方法を検討してください（詳細は `heretic/src/heretic/main.py` の復元ロジック参照）。

## 今後の改善

- **Heretic 本体への CLI フラグ追加**：`--auto-resume` フラグを追加して、ノートブック側の依存を減らす（より堅牢）
- **複数プロンプトの自動応答**：trial 選択や保存メニューまで完全自動化する場合は、追加のレスポンスマッピングが必要
- **ジャーナル安全性向上**：`rsync` の部分コピーリスク回避（一時ファイル経由の原子的更新）

## 参考資料

- [Heretic GitHub](https://github.com/p-e-w/heretic)
- [pexpect ドキュメント](https://pexpect.readthedocs.io/)
- [Google Colab FAQ](https://research.google.com/colaboratory/faq.html)

---

**最終更新**: 2026年4月19日
**作成者**: GitHub Copilot (自動生成)
