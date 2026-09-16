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

INSTALL_PYTHON ?= python3.12

.PHONY: all environment clean-dist check-packaging build install

# Default target: build every distribution.
all: build

environment:
	@if [ ! -d .venv ]; then \
		command -v python3.12 >/dev/null 2>&1 || { echo "error: Python 3.12 is required" >&2; exit 1; }; \
		python3.12 -m venv --upgrade-deps .venv; \
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

install:
	@command -v "$(INSTALL_PYTHON)" >/dev/null 2>&1 || { echo "error: $(INSTALL_PYTHON) is required" >&2; exit 1; }
	@$(INSTALL_PYTHON) -m pip install $(PACKAGES)

# --- Per-package build rules -------------------------------------------------
#
# dist/<pkg>/.built stamps a successful build and is rebuilt only when the
# package's own files change. `make build-<pkg>` works on a single package;
# `make build` covers all of them.

define package_rules

.PHONY: build-$1

$1_files := $(shell find $(call dir_of,$1) -type f -not -path '*/__pycache__/*' -not -name '*.pyc')

dist/$1/.built: $(call dir_of,$1)/pyproject.toml $$($1_files) | environment
	@rm -rf -- dist/$1
	@mkdir -p dist/$1
	$(PYTHON) -m build --no-isolation --outdir dist/$1 $(call dir_of,$1)
	@$(PYTHON) -m twine check dist/$1/*
	@touch $$@

build-$1: dist/$1/.built

endef

$(foreach pkg,$(PACKAGES),$(eval $(call package_rules,$(pkg))))
