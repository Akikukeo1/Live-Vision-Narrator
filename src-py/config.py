"""Live-Vision-Narrator の Ollama プロキシ設定。

優先順位で複数ソースから設定を読み込みます:
    1. 環境変数（最優先）
    2. .env ファイル
    3. config.toml ファイル
    4. コード内のデフォルト（最下位）

# TODO: 翻訳内容のレビューを行ってください。
# NOTE: 関数名・変数名は慣習的に英語のまま保持しています。
"""

import sys
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


def load_toml(path: Path) -> dict:
    """TOML 設定ファイルを読み込みます。

    Python 3.11+ の場合は標準の `tomllib` を使用し、それ以前は `tomli` を試します。
    ファイルが見つからない場合は空の dict を返します。
    """
    if not path.exists():
        return {}

    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # Fallback for Python < 3.11
        except ImportError:
            # tomli not installed; skip TOML loading
            return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        # 日本語で警告を出す（動作には影響なし）
        print(f"警告: {path} から TOML 設定の読み込みに失敗しました: {e}")
        return {}


def get_config_path() -> Path:
    """`config.toml` のパスを返します。

    PyInstaller 等で frozen 実行ファイルになっている場合は実行ファイルのディレクトリを参照します。
    それ以外はこのモジュールと同じディレクトリを参照します。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.toml"
    return Path(__file__).parent / "config.toml"


class Settings(BaseSettings):
    """アプリケーション設定。環境変数・.env・TOML に対応します。"""

    # Ollama connection
    ollama_url: str = "http://localhost:11434"
    ollama_generate_path: str = "/api/generate"
    ollama_models_path: str = "/api/tags"

    # デフォルトのモデル推論モード
    default_think: bool = False

    # ログ設定
    log_level: str = "INFO"

    # セッション管理
    model_idle_seconds: int = 2000

    # サーバのバインド先 / ポート
    # host_ip: サーバがバインドするアドレス（0.0.0.0 = 全インターフェース）
    host_ip: str = "0.0.0.0"
    ui_ip: str = "0.0.0.0"
    # api_host: ブラウザからアクセス可能な API ホスト名（UI が接続するために使用）
    api_host: str = "localhost"

    api_port: int = 8000
    ui_port: int = 8001

    # システムプロファイルのファイルパス
    system_default_file: str = "Modelfile"
    system_detailed_file: str = "Modelfile.detailed"

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8"
    )

    @classmethod
    def load_from_file(cls) -> "Settings":
        """TOML ファイルから設定を読み込み、その後環境変数や .env を適用します。

        優先順: 環境変数 > .env > config.toml > デフォルト
        """
        config_path = get_config_path()
        toml_config = load_toml(config_path)

        # Create settings with TOML data first, then BaseSettings will merge
        # environment variables and .env file (which have higher precedence)
        return cls(**toml_config)


def get_settings() -> Settings:
    """Factory function to get application Settings.

    Usage:
        settings = get_settings()
        app.state.settings = settings
    """
    return Settings.load_from_file()
