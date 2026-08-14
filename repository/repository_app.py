from __future__ import annotations

import logging
from pathlib import Path

import pypiserver
from package_docs import is_successful_package_upload, refresh_package_documentation
from pypiserver.bottle_wrapper import bottle

DATA_DIRECTORY = Path("/data")
DOCUMENTATION_DIRECTORY = DATA_DIRECTORY / "docs"
PACKAGE_DOCUMENTATION_DIRECTORY = DATA_DIRECTORY / "package-docs"
PACKAGES_DIRECTORY = DATA_DIRECTORY / "packages"
LOGGER = logging.getLogger(__name__)

application = pypiserver.app(
    roots=[PACKAGES_DIRECTORY],
    password_file=str(DATA_DIRECTORY / "auth" / "htpasswd"),
    authenticate=["update"],
    disable_fallback=True,
    health_endpoint="/health",
    welcome_msg=(DATA_DIRECTORY / "welcome.html").read_text(encoding="utf-8"),
)

refresh_package_documentation(PACKAGES_DIRECTORY, PACKAGE_DOCUMENTATION_DIRECTORY)


@application.hook("after_request")
def refresh_documentation_after_upload() -> None:
    if not is_successful_package_upload(
        method=bottle.request.method,
        path=bottle.request.path,
        status_code=bottle.response.status_code,
        action=bottle.request.forms.get(":action"),
    ):
        return
    try:
        refresh_package_documentation(
            PACKAGES_DIRECTORY, PACKAGE_DOCUMENTATION_DIRECTORY
        )
    except Exception:
        LOGGER.exception("failed to refresh uploaded package documentation")


@application.get("/docs")
def documentation_redirect() -> None:
    bottle.redirect("/docs/")


@application.get("/docs/")
def documentation_index() -> object:
    return bottle.static_file("index.html", root=DOCUMENTATION_DIRECTORY)


@application.get("/docs/packages")
def package_documentation_redirect() -> None:
    bottle.redirect("/docs/packages/")


@application.get("/docs/packages/")
def package_documentation_index() -> object:
    return bottle.static_file("index.html", root=PACKAGE_DOCUMENTATION_DIRECTORY)


@application.get("/docs/packages/<project>/")
def package_documentation_project(project: str) -> object:
    return bottle.static_file(
        f"{project}/index.html", root=PACKAGE_DOCUMENTATION_DIRECTORY
    )


@application.get("/docs/<directory:path>/")
def documentation_directory(directory: str) -> object:
    return bottle.static_file(
        f"{directory.rstrip('/')}/index.html", root=DOCUMENTATION_DIRECTORY
    )


@application.get("/docs/<filename:path>")
def documentation_file(filename: str) -> object:
    return bottle.static_file(filename, root=DOCUMENTATION_DIRECTORY)
