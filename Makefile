.PHONY: install
install:
	python3 -m pip install --require-virtualenv --upgrade pip
	python3 -m pip install --require-virtualenv --upgrade -r requirements-dev.txt $(PIP_INSTALL_ARGS)

# run linters
.PHONY: lint
lint:
	pre-commit run -a --show-diff-on-failure --color=always

# build package
.PHONY: build
build:
	python3 -m build

# upload package to PyPI
.PHONY: upload
upload:
	if ! command -v twine >/dev/null 2>&1; then python3 -m pip install --require-virtualenv --upgrade twine; fi
	twine upload --skip-existing dist/*

# release package to PyPI
.PHONY: release
release: build upload
