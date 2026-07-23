CHART_DIR := helm
CHART_NAME := rag-platform
VALUES_FILE := values.yaml
CHART_VERSION := $(shell helm show chart $(CHART_DIR) | awk '/^version:/ {print $$2}')

RELEASE_NAME := rag

REGISTRY_HOST := ghcr.io
OCI_REGISTRY := $(REGISTRY_HOST)/cnapcloud/charts

CNPG_NAMESPACE := cnpg-system

.PHONY: deps lint package login push check-cnpg install upgrade uninstall clean

deps:
	helm dependency build $(CHART_DIR)

lint: deps
	helm lint $(CHART_DIR)

package: deps
	mkdir -p dist
	helm package $(CHART_DIR) --destination dist

login:
	gh auth token | helm registry login $(REGISTRY_HOST) --username $(shell gh api user -q .login) --password-stdin

push: package login
	helm push dist/$(CHART_NAME)-$(CHART_VERSION).tgz oci://$(OCI_REGISTRY)

check-cnpg:
	@kubectl get namespace $(CNPG_NAMESPACE) >/dev/null 2>&1 || \
		(echo "cnpg-operator not found: namespace '$(CNPG_NAMESPACE)' does not exist." && \
		 echo "Install it first — see README.md > Prerequisites." && exit 1)

install: check-cnpg
	helm upgrade --install $(RELEASE_NAME) \
		oci://$(OCI_REGISTRY)/$(CHART_NAME) \
		--version $(CHART_VERSION) \
		-n $(RELEASE_NAME) \
		--create-namespace \
		-f $(CHART_DIR)/values.yaml \
		-f $(VALUES_FILE)

upgrade: check-cnpg
	helm upgrade --install $(RELEASE_NAME) \
		oci://$(OCI_REGISTRY)/$(CHART_NAME) \
		--version $(CHART_VERSION) \
		-n $(RELEASE_NAME) \
		--create-namespace \
		-f $(CHART_DIR)/values.yaml \
		-f $(VALUES_FILE)

uninstall:
	helm uninstall $(RELEASE_NAME) -n $(RELEASE_NAME)

clean:
	rm -rf $(CHART_DIR)/charts
	rm -rf dist