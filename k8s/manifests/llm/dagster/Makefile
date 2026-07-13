.PHONY: pull preview diff apply delete namespace build push help

export DEPLOY_ENV ?= dev
KUBECTL := kubectl
KUSTOMIZE ?= kustomize
GITOPS_OVERLAYS := kustomize/overlays/$(DEPLOY_ENV)

REGISTRY := cnapcloud
IMAGE := dagster
DAGSTER_VERSION := 1.13.8
FULL_IMAGE := $(REGISTRY)/$(IMAGE):$(DAGSTER_VERSION)

build: ## Build dagster image
	docker build \
		--build-arg DAGSTER_VERSION=$(DAGSTER_VERSION) \
		-t $(FULL_IMAGE) \
		-t $(REGISTRY)/$(IMAGE):latest .

push: ## Push dagster image to cnapcloud registry
	docker push $(FULL_IMAGE)
	docker push $(REGISTRY)/$(IMAGE):latest

namespace: ## Create Kubernetes namespace 'llm' if it doesn't exist
	$(KUBECTL) create namespace llm || true

pull: ## Pull helm chart
	rm -rf kustomize/base/helm/dagster
	helm repo add dagster https://dagster-io.github.io/helm
	helm repo update
	helm pull dagster/dagster \
		--version 1.13.8 \
		--untar \
		--destination kustomize/base/helm

delete: ## Delete workload
	-$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) delete -f -

apply: namespace ## Deploy workload
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) apply --force-conflicts --server-side=true -f -

preview: ## Preview generated manifests
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS)

diff: ## Show workload diff
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) diff -f - || true

help: ## Show available targets and descriptions
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk -F ':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'