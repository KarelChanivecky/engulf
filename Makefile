PYTHON := .venv/bin/python
PACKAGE_DIRS := \
	engulf-api \
	engulf \
	engulf-executable-wrapper-api \
	engulf-executable-wrapper \
	plugins/engulf-plugin-list
PACKAGE_NAMES := \
	engulf-api \
	engulf \
	engulf-executable-wrapper-api \
	engulf-executable-wrapper \
	engulf-plugin-list
INSTALL_PYTHON ?= python3.14

.PHONY: environment clean-dist build publish install test-repository

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

build: environment clean-dist
	@set -eu; \
	for package in $(PACKAGE_DIRS); do \
		output="dist/$$(basename "$$package")"; \
		mkdir -p "$$output"; \
		$(PYTHON) -m build --no-isolation --outdir "$$output" "$$package"; \
	done
	@$(PYTHON) -m twine check dist/*/*

publish: build
	@test -n "$${TWINE_REPOSITORY_URL:-}" || { echo "error: TWINE_REPOSITORY_URL is required" >&2; exit 1; }
	@$(PYTHON) -m twine upload --repository-url "$$TWINE_REPOSITORY_URL" dist/*/*

install:
	@command -v "$(INSTALL_PYTHON)" >/dev/null 2>&1 || { echo "error: $(INSTALL_PYTHON) is required" >&2; exit 1; }
	@$(INSTALL_PYTHON) -m pip install $(PACKAGE_NAMES)

test-repository:
	python3 -m unittest discover -s repository/tests -v
	bash -n repository.sh build.sh publish.sh
