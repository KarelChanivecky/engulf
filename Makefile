PYTHON := .venv/bin/python
PACKAGES := \
	engulf-api \
	engulf \
	engulf-executable-wrapper-api \
	engulf-executable-wrapper \
	engulf-plugin-list

# Package name -> source directory (defaults to the package name)
DIR_engulf-plugin-list := plugins/engulf-plugin-list

dir_of = $(or $(DIR_$1),$1)

INSTALL_PYTHON ?= python3.14

.PHONY: all environment clean-dist build publish install test-repository

# Default target: build everything, then upload whatever was not published yet.
all: build publish

environment:
	@if [ ! -d .venv ]; then \
		command -v python3.14 >/dev/null 2>&1 || { echo "error: Python 3.14 is required" >&2; exit 1; }; \
		python3.14 -m venv --upgrade-deps .venv; \
	elif [ ! -x "$(PYTHON)" ]; then \
		echo "error: .venv is not a usable virtual environment" >&2; \
		exit 1; \
	fi
	@$(PYTHON) -m pip install --group dev

clean-dist:
	rm -rf -- dist

build: $(PACKAGES:%=dist/%/.built)

publish: $(PACKAGES:%=publish-%)

install:
	@command -v "$(INSTALL_PYTHON)" >/dev/null 2>&1 || { echo "error: $(INSTALL_PYTHON) is required" >&2; exit 1; }
	@$(INSTALL_PYTHON) -m pip install $(PACKAGES)

test-repository:
	python3 -m unittest discover -s repository/tests -v
	bash -n repository.sh build.sh publish.sh

# --- Per-package build / publish rules --------------------------------------
#
# dist/<pkg>/.built stamps a successful build (rebuilt only when the package's
# own files change); dist/<pkg>/.published stamps a successful upload of that
# build (removed by every rebuild, so new artifacts are always republished).
# `make build-<pkg>` / `make publish-<pkg>` work on a single package;
# `make build` / `make publish` cover all of them.

define package_rules

.PHONY: build-$1 publish-$1

$1_files := $(shell find $(call dir_of,$1) -type f -not -path '*/__pycache__/*' -not -name '*.pyc')

dist/$1/.built: $(call dir_of,$1)/pyproject.toml $$($1_files) | environment
	@rm -rf -- dist/$1
	@mkdir -p dist/$1
	$(PYTHON) -m build --no-isolation --outdir dist/$1 $(call dir_of,$1)
	@$(PYTHON) -m twine check dist/$1/*
	@touch $$@

dist/$1/.published: dist/$1/.built
	@test -n "$$$${TWINE_REPOSITORY_URL:-}" || { echo "error: TWINE_REPOSITORY_URL is required" >&2; exit 1; }
	@test -n "$$$${TWINE_USERNAME:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	@test -n "$$$${TWINE_PASSWORD:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	$(PYTHON) twine_upload.py upload --skip-existing --repository-url "$$$$TWINE_REPOSITORY_URL" dist/$1/*
	@touch $$@

build-$1: dist/$1/.built

# The .published stamp short-circuits repeat uploads of an unchanged build;
# --skip-existing (via twine_upload.py) additionally lets the server confirm
# freshness when the stamp is missing but the artifacts were already uploaded.
publish-$1: dist/$1/.published

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
