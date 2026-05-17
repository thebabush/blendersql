BLENDER ?= blender
DEV_LINK := $(HOME)/Library/Application Support/Blender/5.1/extensions/user_default/blendersql

.PHONY: wheels build test lint typecheck clean install-dev

wheels:
	uv run python scripts/fetch_wheels.py

build:
	mkdir -p dist
	cd blendersql && $(BLENDER) --command extension build --split-platforms --output-dir ../dist/

test:
	uv run pytest tests/

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy .

clean:
	rm -rf dist/ __pycache__ .pytest_cache .ruff_cache

install-dev:
	mkdir -p "$(dir $(DEV_LINK))"
	ln -sfn "$(CURDIR)/blendersql" "$(DEV_LINK)"
