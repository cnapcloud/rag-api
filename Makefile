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
	$(PYTHON) -m venv $(VENV)
	@echo "Created virtualenv at $(VENV)"

install: env
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

COMPOSE = docker compose -f docker/docker-compose.yml

docker-build:
	docker build -t $(IMAGE) -t $(IMAGE_VERSIONED) .

docker-push:
	docker push $(IMAGE)
	docker push $(IMAGE_VERSIONED)

docker-run:
	docker run --rm -p 8000:8000 --name rag-api $(IMAGE)

test: install
	PYTHONPATH=src $(PY) -m pytest -q

compile:
	# Build a wheel
	$(PY) -m pip install --upgrade build
	$(PY) -m build

clean:
	rm -rf build dist *.egg-info $(VENV)
