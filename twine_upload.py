"""twine upload with --skip-existing support for our self-hosted repository.

twine's duplicate detection already handles pypiserver (it treats an HTTP 409
response as "already exists"), but twine 7 refuses --skip-existing unless the
repository URL starts with the official PyPI/TestPyPI hosts
(Settings.verify_feature_capability). Our server is a pypiserver, so the
capability is there and only the URL allowlist blocks it. Lift the allowlist
before dispatching to the regular twine CLI; when twine lets third-party
repositories opt into --skip-existing, this wrapper can be deleted.
"""

from twine.__main__ import main as twine_main
from twine.settings import Settings

Settings.verify_feature_capability = lambda self: None  # noqa: E731

if __name__ == "__main__":
    twine_main()
