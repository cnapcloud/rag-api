.PHONY: install sync lock build push test lint typecheck compile clean

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

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy .

compile:
	$(UV) build

docker-build:
	docker buildx build --platform linux/arm64 \
		--cache-from type=registry,ref=$(CACHE_IMAGE) \
		-t $(IMAGE) --load .

# Builds and pushes directly via --push, bypassing the local image store — works with
# both the default local driver and remote drivers (e.g. CI's kubernetes buildx driver,
# which has no local daemon for docker-build's --load / a plain `docker push` to find).
# --cache-to/--cache-from with type=registry stores the layer cache as a separate
# tag in the registry, so it survives the CI builder pod being ephemeral.
docker-push:
	docker buildx build --platform linux/arm64 \
		--cache-from type=registry,ref=$(CACHE_IMAGE) \
		--cache-to type=registry,ref=$(CACHE_IMAGE),mode=max \
		-t $(IMAGE) -t $(IMAGE_LATEST) --push .

clean:
	rm -rf build dist *.egg-info .venv
