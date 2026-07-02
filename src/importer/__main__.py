import httpx2
from zipfile import ZipFile
import logging
from settings_importer import importer_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


openai_api_key = importer_settings.deepl_api_key
download_link = importer_settings.nextcloud_download_link
archive_output_path = importer_settings.archive_output_file
extract_output_dir = importer_settings.base_dir


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
        zip_ref.extractall(extract_output_dir)


def main():
    download_file()
    extract_zip()


main()
