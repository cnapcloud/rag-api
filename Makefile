.PHONY: env install docker-build docker-push docker-run docker-up docker-down test compile clean

PYTHON ?= python3
VENV ?= .venv
PY = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

IMAGE_ORG ?= cnapcloud
IMAGE_NAME ?= rag-api
IMAGE_TAG ?= latest
VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/v\1/')
IMAGE = $(IMAGE_ORG)/$(IMAGE_NAME):$(IMAGE_TAG)
IMAGE_VERSIONED = $(IMAGE_ORG)/$(IMAGE_NAME):$(VERSION)

env:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@echo "Virtualenv at $(VENV)"

install: env
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

COMPOSE = docker compose -f docker/docker-compose.yml

build:
	docker buildx build --platform linux/arm64 -t $(IMAGE) -t $(IMAGE_VERSIONED) .

push: build
	docker push $(IMAGE)
	docker push $(IMAGE_VERSIONED)

test: install
	PYTHONPATH=src $(PY) -m pytest -q

compile:
	# Build a wheel
	$(PY) -m pip install --upgrade build
	$(PY) -m build

clean:
	rm -rf build dist *.egg-info $(VENV)
