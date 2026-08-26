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

# Publish each package only when its freshly built tree has not been uploaded
# yet. twine --skip-existing is not usable here: it requires server API support
# our repository lacks, so freshness is tracked with a .published stamp that
# every rebuild invalidates.
publish: $(PACKAGES:%=dist/%/.published)

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
	$(PYTHON) -m twine upload --repository-url "$$$$TWINE_REPOSITORY_URL" dist/$1/*
	@touch $$@

build-$1: dist/$1/.built

# Force an upload attempt even when nothing was rebuilt (e.g. a previous
# publish failed after build, or the .published stamp was deleted manually):
# remove dist/<pkg>/.published and re-run, since the publish recipe is skipped
# whenever that stamp is up to date.
publish-$1: dist/$1/.published

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
