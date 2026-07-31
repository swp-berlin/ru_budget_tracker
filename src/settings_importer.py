from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImporterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env.importer",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    deepl_api_key: str
    nextcloud_download_link: str
    # is raw_dir - extract_output_path: Path = Path("data") / "import_files" / "raw"

    base_dir: Path = Path("data") / "import_files"

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


# deepl_api_key / nextcloud_download_link come from the environment (.env.importer).
importer_settings = ImporterSettings()  # ty: ignore[missing-argument]
