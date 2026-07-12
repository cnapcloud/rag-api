.PHONY: pull preview diff apply delete namespace help

export DEPLOY_ENV ?= dev
KUBECTL := kubectl
KUSTOMIZE ?= kustomize
GITOPS_OVERLAYS := kustomize/overlays/$(DEPLOY_ENV)

namespace: ## Create Kubernetes namespace 'llm'
	$(KUBECTL) create namespace llm || true

delete: ## Delete workload
	-$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) delete -f -

apply: namespace ## Deploy workload
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) apply --force-conflicts --server-side=true -f -

preview: ## Preview generated manifests
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS)

diff: ## Show workload diff
	$(KUSTOMIZE) build --enable-alpha-plugins $(GITOPS_OVERLAYS) | $(KUBECTL) diff -f - || true

run-ollama: ## Run Ollama server.
	export OLLAMA_HOST=0.0.0.0:11434 && \
	export OLLAMA_NUM_PARALLEL=2 && \
	export OLLAMA_MAX_LOADED_MODELS=3 && \
	OLLAMA_DEBUG=1 ollama serve

help: ## Show available targets and descriptions
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk -F ':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'