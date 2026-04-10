"""Configuration for Live-Vision-Narrator Ollama Proxy.

Loads settings from multiple sources with precedence:
    1. Environment variables (highest priority)
    2. .env file
    3. config.toml file
    4. Code defaults (lowest priority)
"""

import sys
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


def load_toml(path: Path) -> dict:
    """Load TOML configuration file.

    Supports Python 3.11+ with tomllib, falls back to tomli for earlier versions.
    Returns empty dict if file not found.
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
        print(f"Warning: Failed to load TOML config from {path}: {e}")
        return {}


def get_config_path() -> Path:
    """Get the path to config.toml.

    For frozen (PyInstaller) executables, uses the directory of the executable.
    Otherwise, uses the directory containing this config.py file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.toml"
    return Path(__file__).parent / "config.toml"


class Settings(BaseSettings):
    """Application settings with environment variable and TOML support."""

    # Ollama connection
    ollama_url: str = "http://localhost:11434"
    ollama_generate_path: str = "/api/generate"
    ollama_models_path: str = "/api/tags"

    # Model warmup
    warmup_model: str | None = None

    # Default model inference mode
    default_think: bool = False

    # Logging
    log_level: str = "INFO"

    # Session management
    model_idle_seconds: int = 600

    # System profile file paths
    system_default_file: str = "Modelfile"
    system_detailed_file: str = "Modelfile.detailed"

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8"
    )

    @classmethod
    def load_from_file(cls) -> "Settings":
        """Load settings from TOML file, then apply environment variables/env file.

        Precedence: environment variables > .env > config.toml > defaults
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
