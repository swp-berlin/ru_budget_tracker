# Alembic
This directory contains Alembic migration scripts for managing database schema changes.
Alembic is a lightweight database migration tool for usage with SQLAlchemy.

## Table of Contents
- [Alembic](#alembic)
  - [Table of Contents](#table-of-contents)
  - [Alembic Configuration](#alembic-configuration)
  - [Creating Migrations](#creating-migrations)
  - [Applying Migrations](#applying-migrations)
  - [Downgrading Migrations](#downgrading-migrations)

## Alembic Configuration
The Alembic configuration file `alembic.ini` is located in the root directory of the project.
The main Alembic environment script is located at `src/alembic/env.py`. This script sets up the Alembic context and connects to the database using the SQLAlchemy engine defined in `src/database/sessions.py`.
Migration scripts are stored in the `src/alembic/versions/` directory. Each migration script is named with a unique identifier (4 digits, an underscore and a descriptive name) and contains the necessary upgrade and downgrade functions to apply or revert schema changes.

## Creating Migrations
To create a new migration, use the Alembic command-line tool. First, ensure that you have Alembic installed in your development environment. Then, run the following command from the root directory of the project and make sure to provide a descriptive message for the migration as well as the next increment of the revision id:

```bash
make alembic-revision m="descriptive_message" rev-id="0001"
```

This command will generate a new migration script in the `src/alembic/versions/` directory. You can then edit the generated script to define the specific schema changes needed for your migration.

## Applying Migrations
To apply the latest migrations to the database, use the following command:

```bash
make alembic-upgrade
```

## Downgrading Migrations
To revert the last applied migration, use the following command:

```bash
make alembic-downgrade
```