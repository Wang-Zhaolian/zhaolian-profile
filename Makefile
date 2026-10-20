.PHONY: validate lint test

validate:
	uv run academic-profile validate

lint:
	uv run academic-profile lint

test:
	uv run pytest
