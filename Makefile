.PHONY: install dev test lint format typecheck clean run

install:
	uv sync

dev:
	uv sync --extra dev

run:
	uv run coding-agent

test:
	uv run pytest

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

typecheck:
	uv run mypy src

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
