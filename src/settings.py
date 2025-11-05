from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class Database(BaseModel):
    """SQLite database settings."""

    directory: Path = Path("data")
    file_name: str = "budget.db"

    @property
    def _file_path(self) -> str:
        """
        Full path to the SQLite database file.
        Parent directories are created if they do not exist.
        """
        full_path = self.directory / self.file_name
        # Windows compatibility?
        return full_path.as_posix()

    @property
    def sync_dsn(self) -> str:
        """
        DSN for synchronous SQLite connections.
        """
        return f"sqlite:///{self._file_path}"

    @property
    def async_dsn(self) -> str:
        """
        DSN for asynchronous SQLite connections.
        """
        return f"sqlite+aiosqlite:///{self._file_path}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )
    database: Database = Database()


settings = Settings()
