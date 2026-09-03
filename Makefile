.PHONY: install sync lock check-lock build push test lint typecheck compile clean docker-build docker-push

UV = uv

IMAGE_ORG ?= cnapcloud
IMAGE_NAME ?= rag-api
IMAGE_TAG ?= $(shell git rev-parse --short=4 HEAD)
IMAGE = $(IMAGE_ORG)/$(IMAGE_NAME):$(IMAGE_TAG)
IMAGE_LATEST = $(IMAGE_ORG)/$(IMAGE_NAME):latest
CACHE_IMAGE = $(IMAGE_ORG)/$(IMAGE_NAME):buildcache

install:
	$(UV) sync --extra dev

sync:
	$(UV) sync --frozen --extra dev

lock:
	$(UV) lock

# Fail fast if uv.lock is out of date w.r.t. pyproject.toml. The Docker build runs
# `uv sync --frozen`, which installs strictly from uv.lock and never re-resolves, so a stale
# lock silently ships an image missing newly-added deps. Run `make lock` (and commit) first.
check-lock:
	$(UV) lock --check

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy .

compile:
	$(UV) build

docker-build: check-lock
	docker buildx build --platform linux/arm64 \
		--cache-from type=registry,ref=$(CACHE_IMAGE) \
		-t $(IMAGE) --load .

# Builds and pushes directly via --push, bypassing the local image store — works with
# both the default local driver and remote drivers (e.g. CI's kubernetes buildx driver,
# which has no local daemon for docker-build's --load / a plain `docker push` to find).
# --cache-to/--cache-from with type=registry stores the layer cache as a separate
# tag in the registry, so it survives the CI builder pod being ephemeral.
docker-push: check-lock
	docker buildx build --platform linux/arm64 \
		--provenance=false --sbom=false \
		--cache-from type=registry,ref=$(CACHE_IMAGE) \
		--cache-to type=registry,ref=$(CACHE_IMAGE),mode=max \
		-t $(IMAGE) -t $(IMAGE_LATEST) --push .

clean:
	rm -rf build dist *.egg-info .venv
