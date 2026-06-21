.PHONY: install sync lock build push test compile clean

UV = uv

IMAGE_ORG ?= cnapcloud
IMAGE_NAME ?= rag-api
IMAGE_TAG ?= latest
VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/v\1/')
IMAGE = $(IMAGE_ORG)/$(IMAGE_NAME):$(IMAGE_TAG)
IMAGE_VERSIONED = $(IMAGE_ORG)/$(IMAGE_NAME):$(VERSION)

install:
	$(UV) sync --extra dev

sync:
	$(UV) sync --frozen --extra dev

lock:
	$(UV) lock

COMPOSE = docker compose -f docker/docker-compose.yml

build:
	docker buildx build --platform linux/arm64 -t $(IMAGE) -t $(IMAGE_VERSIONED) .

push: build
	docker push $(IMAGE)
	docker push $(IMAGE_VERSIONED)

test:
	$(UV) run pytest -q

compile:
	$(UV) build

clean:
	rm -rf build dist *.egg-info .venv
