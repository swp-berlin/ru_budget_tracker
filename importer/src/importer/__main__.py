import httpx2
from zipfile import ZipFile
from dotenv import dotenv_values

config = dotenv_values(".env")
download_link = config.get("NEXTCLOUD_DOWNLOAD_LINK")
# username = config.get("NEXTCLOUD_USERNAME")
# password = config.get("NEXTCLOUD_PASSWORD")
archive_output_path = config.get("ARCHIVE_OUTPUT_PATH", "output.zip")
extract_output_path = config.get("EXTRACT_OUTPUT_PATH", "output")

def download_file():
    """
    :raises httpx2.HTTPStatusError: If the HTTP request returned an unsuccessful status code.
    :raises FileExistsError: If the file already exists at the specified path.
    :raises ValueError: if the decoding fails
    :raises OSError: If there is an error writing to the file.
    """
    with httpx2.stream("GET", download_link, follow_redirects=True) as r:
        r.raise_for_status()
        with open(archive_output_path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)

def extract_zip():
    """"
    :raises FileExistsError: If mode is 'x' and file refers to an existing file
    """
    with ZipFile(archive_output_path, "r") as zip_ref:
        zip_ref.extractall(extract_output_path)

def main():
    download_file()
    extract_zip()

main()