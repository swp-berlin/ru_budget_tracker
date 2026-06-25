# RU Budget Tracker Importer

Responsible to import Data from Nextcloud and build the sqlite budget.db requried by the app.

### Required Env Vars

| Name                    | Value | Description                                                                                                                                    |
| ----------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| NEXTCLOUD_DOWNLOAD_LINK | URL   | External Nextcloud Link to the raw dir (should contain: conversion_tables, laws, reports, totals), e.g. https://nextcloud.de/s/TrAyKCrS9aa6LFD |
| ARCHIVE_OUTPUT_PATH     | PATH  | Path where to store the downloaded archive, e.g. /tmp/ru_budget_raw.zip                                                                        |
| EXTRACT_OUTPUT_PATH     | PATH  | Path where the extracted archive data is stored, e.g. /tmp/ru_budget_raw                                                                       |

### How to Build and Run Examples

#### build

`podman build -t importer_t -f Dockerfile.importer .`

#### Run

1. create a .env file (see [Required Env Vars](#required-env-vars))

```sh
# .env example
NEXTCLOUD_DOWNLOAD_LINK=...
ARCHIVE_OUTPUT_PATH=/tmp/ru_budget_raw.zip 
EXTRACT_OUTPUT_PATH=/tmp/ru_budget_raw
```
2. run container

```sh
# UID = your user id
# GID = you group id
# check it out via `id` in terminal
# the mapping keep-id is required to give the unprivileged user `appuser`
# write access the the bind-mounted volume 

podman run -it \
    --userns=keep-id:uid=UID,gid=GID \
    -v ./cache:/tmp/ru_budget_raw \
    -v ./.env:/home/appuser/app/.env \
    importer_t \
    /bin/bash
```
