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


class AppSettings(BaseModel):
    """Application settings."""

    url_base_pathname: str = "/ru-budget-tracker/"


class Settings(BaseSettings):
    """
    Settings for the application, including database and app settings.
    Reads from environment variables and .env file, with support for nested settings
    using double underscores as delimiters.

    Example environment variable for nested settings:
    DATABASE__DIRECTORY=/path/to/database
    DATABASE__FILE_NAME=budget.db
    APP__URL_BASE_PATHNAME=/ru-budget-tracker
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )
    # DeepL API key for translation scripts (optional)
    deepl_api_key: str | None = None
    database: Database = Field(default_factory=lambda: Database())
    app: AppSettings = Field(default_factory=lambda: AppSettings())

class ImporterSettings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file="../.env.importer",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    deepl_api_key: str
    nextcloud_download_link: str
    #is raw_dir - extract_output_path: Path = Path("data") / "import_files" / "raw"

    base_dir: Path = Path("data") / "import_files"
    database: Database = Field(default_factory=lambda: Database())

    @property
    def raw_dir(self) -> Path:
        return self.base_dir / "raw"
    
    @property
    def archive_output_file(self) -> Path:
        return self.base_dir / "archive.zip"
    
    # @property
    # def conversion_tables_dir(self) -> Path:
    #     return self.base_dir / "conversion_tables"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "clean"

    @property
    def translation_dir(self) -> Path:
        return self.data_dir / "translations"
    
    @property
    def totals_report_file(self) -> Path:
        return self.raw_dir / "totals/totals_report_2026.xlsx"
    
    @property
    def totals_law_file(self) -> Path:
        return self.raw_dir / "totals/totals_law_2026.xlsx"
    
    # @property
    # def laws_dir(self) -> Path:
    #     return self.data_dir / "laws"
    
    # @property
    # def reports_dir(self) -> Path:
    #     return self.data_dir / "reports"



settings = Settings()
