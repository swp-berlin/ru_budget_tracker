# RU Budget Tracker Importer

Responsible to import Data from Nextcloud and build the sqlite budget.db requried by the app.

### Required Env Vars

| Name                    | Value | Description                                                                                                                                    |
| ----------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| NEXTCLOUD_DOWNLOAD_LINK | URL   | External Nextcloud Link to the raw dir (should contain: conversion_tables, laws, reports, totals), e.g. https://nextcloud.de/s/TrAyKCrS9aa6LFD |
| ARCHIVE_OUTPUT_PATH     | PATH  | Path where to store the downloaded archive, e.g. /tmp/ru_budget_raw.zip                                                                        |
| EXTRACT_OUTPUT_PATH     | PATH  | Path where the extracted archive data is stored, e.g. /tmp/ru_budget_raw                                                                       |
| OPENAI_API_KEY          | STR   | OpenAI API Key for translations                                                                                                                |

### Run project

`uv run python -m src.importer`

### How to Build and Run Container Examples

#### build

`podman build -t importer_t -f Dockerfile.importer .`

#### Run

1. create a .env.importer file (see [Required Env Vars](#required-env-vars))

```sh
# .env.importer example
OPENAI_API_KEY=...
NEXTCLOUD_DOWNLOAD_LINK=...
ARCHIVE_OUTPUT_PATH=/tmp/ru_budget_raw.zip 
EXTRACT_OUTPUT_PATH=/app/src/data/import_files
```
2. run container

```sh
# uid = appusers user id (1001)
# gid = appusers group id (1001)
# check it out via `id` in terminal inside the container
# the mapping keep-id is required to give the unprivileged user `appuser`
# write access the the bind-mounted volume 

podman run -it \
    --userns=keep-id:uid=1001,gid=1001 \
    -v ./src/data:/app/src/data:z,shared \
    -v ./.env.importer:/app/.env.importer \
    --env-file=./.env.importer \
    importer_t \
    /bin/bash
```
