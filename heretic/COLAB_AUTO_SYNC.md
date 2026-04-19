# Heretic Colab 自動同期ガイド

このドキュメントは、Google Colab 上で Heretic を実行する際、ランタイム切断に耐える自動チェックポイント同期ワークフローの実装と使用方法を説明します。

## 概要

Colab のランタイムは予告なく切断される可能性があります。Heretic のチェックポイント（`.jsonl`）を安全に保存し、ランタイム復帰後に学習を続行するために以下を実装しました：

1. **起動時復元**：Drive からローカルにチェックポイントを復元
2. **バックグラウンド同期**：実行中に定期的（60 秒間隔）にローカル → Drive に同期
3. **終了時最終同期**：プロセス終了後に最後の同期を実行

## セットアップ手順

### 1. Google Drive マウント（既存セル）

`colab_setup.ipynb` の「Optional: Mount Google Drive」セルを実行します：

```python
from google.colab import drive
drive.mount('/content/drive', force_remount=True)
```

### 2. 初期復元と同期開始（新セル：「Restore from Drive & Start Background Sync」）

以下のセルを実行します。このセルは：
- Drive から `/content/checkpoints` にチェックポイント復元
- バックグラウンドスレッドで 60 秒ごとに同期を開始

```python
#@title Restore from Drive & Start Background Sync (チェックポイント自動同期)
import os
import subprocess
import threading
import time

LOCAL_CKPTS = '/content/checkpoints'
LOCAL_MODELS = '/content/models'
os.makedirs(LOCAL_CKPTS, exist_ok=True)
os.makedirs(LOCAL_MODELS, exist_ok=True)

DRIVE_CKPTS = '/content/drive/MyDrive/heretic/checkpoints'
DRIVE_MODELS = '/content/drive/MyDrive/heretic/models'

print("=== Restoring checkpoints from Drive ===")
os.makedirs(DRIVE_CKPTS, exist_ok=True)
subprocess.run(['rsync', '-av', '--progress', f'{DRIVE_CKPTS}/', f'{LOCAL_CKPTS}/'], check=False)

print("=== Starting background sync thread ===")
SYNC_INTERVAL = 60

def sync_loop():
    while True:
        try:
            subprocess.run(['rsync', '-av', '--progress', f'{LOCAL_CKPTS}/', f'{DRIVE_CKPTS}/'], check=True, timeout=120)
            print(f"[sync] Checkpoints synced to Drive at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"[sync error] {e}")
        time.sleep(SYNC_INTERVAL)

sync_thread = threading.Thread(target=sync_loop, daemon=True, name='checkpoint_sync')
sync_thread.start()
print(f"Background sync started (interval: {SYNC_INTERVAL}s)")
```

### 3. Heretic 実行（修正済みセル：「Run Heretic」）

このセルは以下の機能を持ちます：

- **`--study-checkpoint-dir /content/checkpoints`**：ローカルディレクトリにチェックポイント保存
- **ログ記録**：`heretic_run.log` に実行ログを保存
- **終了時同期**：プロセス終了後に最終同期を実行

```python
#@title Run Heretic (with checkpoint auto-sync & restore)
import subprocess
import os

use_quantization = True
skip_batch_autodetect = True
fixed_batch_size = 128

LOCAL_CKPTS = '/content/checkpoints'
DRIVE_CKPTS = '/content/drive/MyDrive/heretic/checkpoints'

cmd = f"cd {HERETIC_PATH} && uv run --no-sync heretic --model {MODEL_PATH} --study-checkpoint-dir {LOCAL_CKPTS}"
if use_quantization:
    cmd += " --quantization bnb_4bit"
if skip_batch_autodetect:
    cmd += f" --batch-size {fixed_batch_size}"

log_file = f"{HERETIC_PATH}/heretic_run.log"

print(f"Running command: {cmd}")
print(f"Checkpoints saved to: {LOCAL_CKPTS}")
print(f"Log file: {log_file}")

result = subprocess.run(
    f"{cmd} 2>&1 | tee {log_file}",
    shell=True,
    check=False
)

print("=== Final sync to Drive ===")
os.makedirs(DRIVE_CKPTS, exist_ok=True)
subprocess.run(['rsync', '-av', '--progress', f'{LOCAL_CKPTS}/', f'{DRIVE_CKPTS}/'], check=False)
print(f"Final sync completed. Checkpoints saved to Drive: {DRIVE_CKPTS}")
```

## 実行フロー

```
1. [Colab セル] Google Drive マウント
   ↓
2. [Colab セル] Restore & Start Background Sync
   ├─ Drive から /content/checkpoints に復元
   ├─ バックグラウンドスレッド開始（60s 間隔で同期）
   └─ 学習再開時のロードを自動化
   ↓
3. [Colab セル] Run Heretic
   ├─ Heretic を起動
   ├─ ローカル /content/checkpoints に保存
   ├─ バックグラウンド同期により自動バックアップ
   └─ 終了時に最終同期実行
   ↓
4. チェックポイントが Drive に保存され、再開可能
```

## トラブルシューティング

### Q: チェックポイントが Drive に同期されていない

**原因**：
- バックグラウンド同期スレッドがまだ実行されていない（60 秒待つ）
- Drive マウントが切断された

**対処法**：
- バックグラウンド同期が動作しているか確認：`ls -la /content/drive/MyDrive/heretic/checkpoints/`
- 手動で同期：`rsync -av --progress /content/checkpoints/ /content/drive/MyDrive/heretic/checkpoints/`

### Q: ランタイム切断後、チェックポイントから復帰したい

**手順**：
1. Colab を再開
2. 「Google Drive マウント」セルを実行
3. 「Restore from Drive & Start Background Sync」セルを実行（チェックポイントが復元される）
4. 「Run Heretic」セルを実行（自動的に前回の実験が検出され、「Continue the previous run」オプションが提示される）

### Q: ローカルとリモートのファイルが一致しない

**対処法**：
- 手動で整合性チェック：
  ```bash
  rsync -av --checksum --progress /content/checkpoints/ /content/drive/MyDrive/heretic/checkpoints/
  ```

## 技術詳細

### パス構成

| 項目 | パス | 説明 |
|------|------|------|
| ローカルチェックポイント | `/content/checkpoints` | Colab 実行環境内（短期保存、実行中のメイン） |
| Drive チェックポイント | `/content/drive/MyDrive/heretic/checkpoints` | Google Drive（長期保存、バックアップ） |
| ローカルモデルキャッシュ | `/content/models` | ダウンロード済みモデル（オプション） |
| Drive モデルキャッシュ | `/content/drive/MyDrive/heretic/models` | モデルの Drive バックアップ（オプション） |

### 同期間隔

デフォルトは **60 秒**。実行状況に応じて調整：
- 短くする（例：30 秒）：より頻繁にバックアップ、CPU 負荷増加
- 長くする（例：120 秒）：CPU 負荷低減、同期遅延増加

修正箇所：`SYNC_INTERVAL = 60` を変更

### ファイル形式

- Optuna ジャーナル：`--content--models--google--gemma-4-E4B-it.jsonl`（追記形式）
- テキスト形式で安全に部分ロード可能

## 注意点

1. **デーモンスレッド**：バックグラウンド同期はデーモンスレッドで実行。ランタイムが明示的に終了された場合、同期が完了しない可能性があるため、「Run Heretic」セルの終了時同期が重要です。

2. **`rsync` の可用性**：Colab には通常 `rsync` がインストール済み。万が一ない場合は、Python の `shutil.copy2` で代替可能（速度低下）。

3. **ファイル整合性**：複数プロセスが同時に同じファイルを書き込むと不整合が生じる可能性あり。現在の実装では Optuna がファイルロックを管理。

4. **ランタイム切断時**：バックグラウンド同期が非グレースシャットダウンされるため、完全な同期保証はなし。クリティカルな場合は、定期的に手動でセルを実行して同期してください。

## 参考

- Optuna ジャーナル形式：https://optuna.readthedocs.io/en/stable/reference/generated/optuna.storages.JournalFileBackend.html
- Heretic チェックポイント設定：[heretic/src/heretic/config.py](../src/heretic/config.py) の `study_checkpoint_dir` パラメータ
