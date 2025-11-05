alembic-upgrade:
	cd src && uv run alembic upgrade head && cd -
alembic-revision:
	cd src && uv run alembic revision --autogenerate -m "$(m)" --rev-id "$(rev-id)" && cd -
alembic-downgrade:
	cd src && uv run alembic downgrade -1 && cd -