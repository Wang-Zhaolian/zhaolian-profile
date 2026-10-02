.PHONY: validate lint phd ra summer_research domestic internship all test

validate:
	uv run academic-profile validate

lint:
	uv run academic-profile lint

phd ra summer_research domestic internship:
	uv run academic-profile generate $@

all:
	uv run academic-profile generate all

test:
	uv run pytest

