import os
import httpx2
from zipfile import ZipFile
from dotenv import load_dotenv
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ENV_FILE = ".env.importer"

if os.environ.get("OPENAI_API_KEY") is None:
    log.warning(
        "OPENAI_API_KEY environment variable is not set. "
        f"OPENAI_API_KEY must be set via environment variable and not via {ENV_FILE} file. "
        "Because Make requires OPENAI_API_KEY to be set in the environment, and python-dotenv does not automatically set environment variables."
    )

if Path(ENV_FILE).exists():
    load_dotenv(ENV_FILE)
    log.info(f"Loaded environment variables from {ENV_FILE}")

config = {**os.environ}
openai_api_key = config.get("OPENAI_API_KEY")
download_link = config.get("NEXTCLOUD_DOWNLOAD_LINK")
archive_output_path = config.get("ARCHIVE_OUTPUT_PATH")
extract_output_path = config.get("EXTRACT_OUTPUT_PATH")

if (
    not download_link
    or not archive_output_path
    or not extract_output_path
    or not openai_api_key
):
    log.error(
        "Missing required environment variables: NEXTCLOUD_DOWNLOAD_LINK, ARCHIVE_OUTPUT_PATH, EXTRACT_OUTPUT_PATH, OPENAI_API_KEY"
    )
    exit(1)


def download_file():
    """
    :raises httpx2.HTTPStatusError: If the HTTP request returned an unsuccessful status code.
    :raises FileExistsError: If the file already exists at the specified path.
    :raises ValueError: if the decoding fails
    :raises OSError: If there is an error writing to the file.
    """
    log.info("Downloading file from Nextcloud...")

    download_url = download_link + "/download"

    with httpx2.stream("GET", download_url, follow_redirects=True) as r:
        r.raise_for_status()
        with open(archive_output_path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def extract_zip():
    """ "
    :raises FileExistsError: If mode is 'x' and file refers to an existing file
    """
    log.info("Extracting ZIP file...")
    with ZipFile(archive_output_path, "r") as zip_ref:
        zip_ref.extractall(extract_output_path)


def main():
    download_file()
    extract_zip()


main()
