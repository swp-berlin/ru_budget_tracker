from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Database(BaseModel):
    """SQLite database settings."""

    directory: Path = Path("data")
    file_name: str = "budget.db"

    @property
    def _file_path(self) -> Path:
        """
        Full path to the SQLite database file.
        Path is constructed by taking the os into account, resulting in either a
        windows or unix style path.
        Parent directories are created if they do not exist.
        """
        full_path = self.directory / self.file_name

        return full_path

    @property
    def sync_dsn(self) -> str:
        """
        DSN for synchronous SQLite connections.
        """
        return f"sqlite:///{str(self._file_path)}"

    @property
    def async_dsn(self) -> str:
        """
        DSN for asynchronous SQLite connections.
        """
        return f"sqlite+aiosqlite:///{str(self._file_path)}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )
    database: Database = Field(default_factory=lambda: Database())


settings = Settings()
