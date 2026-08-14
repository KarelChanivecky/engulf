from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from repository.package_docs import (
    is_successful_package_upload,
    read_distribution_metadata,
    refresh_package_documentation,
)


class PackageDocumentationTestCase(unittest.TestCase):
    def make_wheel(self, directory: Path, name: str = "Example_Package") -> Path:
        wheel = directory / "example_package-1.2.3-py3-none-any.whl"
        metadata = f"""Metadata-Version: 2.4
Name: {name}
Version: 1.2.3
Summary: An example package
Requires-Python: >=3.14
Requires-Dist: dependency>=2
Project-URL: Documentation, https://docs.example.test/package/
Description-Content-Type: text/markdown

# Example

This text includes <script>alert(1)</script>.

[Safe link](https://example.test/) [unsafe link](javascript:alert(2))
"""
        with zipfile.ZipFile(wheel, mode="w") as archive:
            archive.writestr("example_package-1.2.3.dist-info/METADATA", metadata)
        return wheel

    def test_reads_wheel_metadata_without_extracting_package_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = self.make_wheel(Path(temporary))
            metadata = read_distribution_metadata(wheel)

        self.assertEqual(metadata.name, "Example_Package")
        self.assertEqual(metadata.version, "1.2.3")
        self.assertEqual(metadata.dependencies, ("dependency>=2",))
        self.assertEqual(
            metadata.project_urls,
            (("Documentation", "https://docs.example.test/package/"),),
        )

    def test_refresh_generates_safe_index_and_project_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages = root / "packages"
            output = root / "docs"
            packages.mkdir()
            self.make_wheel(packages)

            refresh_package_documentation(packages, output)

            index = (output / "index.html").read_text(encoding="utf-8")
            project = (output / "example-package" / "index.html").read_text(
                encoding="utf-8"
            )
        self.assertIn("Example_Package", index)
        self.assertIn("An example package", index)
        self.assertIn("dependency&gt;=2", project)
        self.assertIn("<h1>Example</h1>", project)
        self.assertIn('<a href="https://example.test/">Safe link</a>', project)
        self.assertNotIn("<script>", project)
        self.assertNotIn("javascript:", project)
        self.assertIn("alert(1)", project)

    def test_plain_text_description_remains_escaped(self) -> None:
        from repository.package_docs import render_description

        rendered = render_description("<strong>not HTML</strong>", "text/plain")

        self.assertEqual(rendered, "<pre>&lt;strong&gt;not HTML&lt;/strong&gt;</pre>")

    def test_only_successful_file_uploads_trigger_refresh(self) -> None:
        self.assertTrue(
            is_successful_package_upload(
                method="POST", path="/", status_code=200, action="file_upload"
            )
        )
        for method, path, status, action in (
            ("GET", "/", 200, "file_upload"),
            ("POST", "/simple/", 200, "file_upload"),
            ("POST", "/", 400, "file_upload"),
            ("POST", "/", 200, "doc_upload"),
        ):
            self.assertFalse(
                is_successful_package_upload(
                    method=method,
                    path=path,
                    status_code=status,
                    action=action,
                )
            )


if __name__ == "__main__":
    unittest.main()
