# Use Windows PowerShell for all recipes.

set shell := ["powershell", "-NoProfile", "-Command"]

_default:
    @just --list

ruff:
    uvx ruff check --exclude typings
    uvx ruff format --exclude typings

# Run Python type checking with basedpyright.
typecheck:
    uvx basedpyright

# Run prek hooks against all files.
prek:
    uv run prek run --all-files; uv run prek run --all-files

test:
    uv run pytest --doctest-modules

# Run tests with coverage report.
test-cov:
    uv run pytest --doctest-modules --cov=src/pylynxley --cov-report=term-missing
