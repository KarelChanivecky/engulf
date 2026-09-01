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

.PHONY: all environment clean-dist check-packaging build publish install test-repository

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

# Every plugin dependency declared in packaging metadata must come from a
# distribution the project requires. Resolving that needs the dependency wheels
# installed, so this runs here and not in an isolated wheel build.
check-packaging:
	@PYTHONPATH=engulf-api/src:engulf/src $(PYTHON) -m engulf.packaging_check \
		$(foreach package,$(PACKAGES),$(call dir_of,$(package)))

build: check-packaging $(PACKAGES:%=dist/%/.built)

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
# build and is wiped by every rebuild. Stamps can lie (switched
# TWINE_REPOSITORY_URL, wiped/rebuilt server), so check-<pkg>-published — an
# order-only phony prerequisite of .published — runs on every publish
# invocation and re-validates the stamp against the live PEP 503 index,
# deleting it when the server does not host the built files. Once the checker
# has run, Make's mtime logic decides: stamp present and newer than .built →
# skip the upload; stamp removed or wiped by a rebuild → upload. The upload
# still passes --skip-existing as the final arbiter.
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

build-$1: dist/$1/.built

# Order-only phony checker: re-validate the publish against what the server
# actually hosts (simple-index anchors carry the exact file names, version
# included, so this detects "server has 0.1, local has 0.2"; it never clears
# the stamp for the wrong server because the URL is part of the query). An
# unreachable server keeps the stamp — the upload's --skip-existing is the
# final arbiter anyway.
.PHONY: check-$1-published

check-$1-published:
	@test -n "$$$${TWINE_REPOSITORY_URL:-}" || { echo "error: TWINE_REPOSITORY_URL is required" >&2; exit 1; }
	@[ -d dist/$1 ] || exit 0
	@$(PYTHON) check_published.py "$$$$TWINE_REPOSITORY_URL" $1 dist/$1 || \
		if [ $$$$? -eq 1 ]; then rm -f dist/$1/.published; else exit 0; fi

build-$1: dist/$1/.built

dist/$1/.published: dist/$1/.built | check-$1-published
	@test -n "$$$${TWINE_USERNAME:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	@test -n "$$$${TWINE_PASSWORD:-}" || { echo "error: TWINE_USERNAME and TWINE_PASSWORD are required (or run through publish.sh with the managed repository)" >&2; exit 1; }
	$(PYTHON) twine_upload.py upload --skip-existing --repository-url "$$$$TWINE_REPOSITORY_URL" dist/$1/*
	@touch $$@

publish-$1: dist/$1/.published

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
