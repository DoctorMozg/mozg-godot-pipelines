"""Layout rules: marketplace and manifests agree, and plugins never import each other."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Self

import pytest
import repo_rules
from repo_rules import SuiteRules

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_B = {"src/pkg_b/__init__.py": ""}


class SuiteBuilder:
    """Builds a throwaway suite on disk, one plugin at a time, with knobs to break it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._entries: list[dict[str, object]] = []

    def plugin(
        self,
        name: str,
        *,
        version: str = "0.1.0",
        listed_version: str | None = None,
        manifest_name: str | None = None,
        listed: bool = True,
        dependencies: list[object] | str | None = None,
        files: dict[str, str] | None = None,
    ) -> Self:
        folder = self.root / "plugins" / name
        manifest: dict[str, object] = {"name": manifest_name or name, "version": version}
        if dependencies is not None:
            manifest["dependencies"] = dependencies
        self._write(folder / repo_rules.MANIFEST, json.dumps(manifest))
        for relative, text in (files or {}).items():
            self._write(folder / relative, text)
        if listed:
            self.entry(name, f"./plugins/{name}", listed_version)
        return self

    def entry(self, name: str, source: str, version: str | None = None) -> Self:
        entry: dict[str, object] = {"name": name, "source": source}
        if version is not None:
            entry["version"] = version
        self._entries.append(entry)
        return self

    def build(self) -> SuiteRules:
        market = {"name": "test-market", "plugins": self._entries}
        self._write(self.root / repo_rules.MARKETPLACE, json.dumps(market))
        return SuiteRules(self.root)

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def suite(tmp_path: Path) -> SuiteBuilder:
    return SuiteBuilder(tmp_path)


class TestManifests:
    def test_consistent_suite_has_no_problems(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha").plugin("beta").plugin("bundle", dependencies=["alpha", "beta"])
        assert suite.build().problems() == []

    def test_entry_without_plugin_folder_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha").entry("ghost", "./plugins/ghost")
        assert suite.build().problems() == [
            "marketplace entry ghost: source ./plugins/ghost has no plugin folder"
        ]

    def test_version_in_marketplace_entry_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", version="0.2.0", listed_version="0.2.0")
        assert suite.build().problems() == [
            "marketplace entry alpha: version belongs in plugin.json only"
        ]

    def test_name_mismatch_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", manifest_name="other")
        assert suite.build().problems() == [
            "marketplace entry alpha: plugin.json names it differently",
            "plugins/alpha is not listed in the marketplace",
        ]

    def test_unlisted_plugin_folder_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha").plugin("beta", listed=False)
        assert suite.build().problems() == ["plugins/beta is not listed in the marketplace"]

    @pytest.mark.parametrize(
        "dependencies",
        [["missing"], ["bundle"], [{"name": "missing"}]],
        ids=["unknown", "itself", "object form"],
    )
    def test_bad_dependency_is_reported(
        self, suite: SuiteBuilder, dependencies: list[object]
    ) -> None:
        suite.plugin("alpha").plugin("bundle", dependencies=dependencies)
        problems = suite.build().problems()
        assert len(problems) == 1
        assert problems[0].startswith("plugins/bundle depends on unknown ")

    def test_dependencies_must_be_a_list_even_when_the_text_names_a_plugin(
        self, suite: SuiteBuilder
    ) -> None:
        suite.plugin("alpha").plugin("bundle", dependencies="alpha")
        assert suite.build().problems() == ["plugins/bundle: 'dependencies' must be a list"]

    def test_dependency_in_object_form_resolves(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha").plugin("bundle", dependencies=[{"name": "alpha", "version": "1"}])
        assert suite.build().problems() == []

    def test_missing_marketplace_is_one_clear_problem(self, tmp_path: Path) -> None:
        (tmp_path / "plugins").mkdir()
        problems = SuiteRules(tmp_path).problems()
        assert len(problems) == 1
        assert problems[0].endswith("marketplace.json is missing")

    def test_malformed_marketplace_is_reported(self, tmp_path: Path) -> None:
        market = tmp_path / repo_rules.MARKETPLACE
        market.parent.mkdir(parents=True)
        market.write_text("{not json", encoding="utf-8")
        assert "cannot be read" in SuiteRules(tmp_path).problems()[0]

    def test_marketplace_plugins_must_be_a_list(self, tmp_path: Path) -> None:
        market = tmp_path / repo_rules.MARKETPLACE
        market.parent.mkdir(parents=True)
        market.write_text('{"plugins": {}}', encoding="utf-8")
        assert SuiteRules(tmp_path).problems() == [
            f"{repo_rules.MARKETPLACE}: 'plugins' must be a list"
        ]

    def test_plugin_folder_without_manifest_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha")
        (suite.root / "plugins" / "stray").mkdir()
        problems = suite.build().problems()
        assert len(problems) == 1
        assert problems[0].endswith("plugin.json is missing")


class TestImports:
    def test_plugin_importing_another_plugins_package_is_reported(
        self, suite: SuiteBuilder
    ) -> None:
        suite.plugin("alpha", files={"src/pkg_a/mod.py": "import pkg_b\n"})
        suite.plugin("beta", files=PKG_B)
        assert suite.build().problems() == [
            "plugins/alpha/src/pkg_a/mod.py imports pkg_b, which belongs to plugin beta"
        ]

    @pytest.mark.parametrize(
        "source",
        [
            "from pkg_b.sub import thing\n",
            "import pkg_b.sub as renamed\n",
            "def late() -> None:\n    import pkg_b\n",
        ],
        ids=["from-import", "aliased submodule", "import inside a function"],
    )
    def test_every_import_form_is_detected(self, suite: SuiteBuilder, source: str) -> None:
        suite.plugin("alpha", files={"src/pkg_a/mod.py": source}).plugin("beta", files=PKG_B)
        assert len(suite.build().problems()) == 1

    def test_plugin_tests_are_scanned_too(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", files={"tests/test_alpha.py": "import pkg_b\n"})
        suite.plugin("beta", files=PKG_B)
        assert len(suite.build().problems()) == 1

    @pytest.mark.parametrize(
        "source",
        ["import pkg_a\n", "import json\n", "from . import sibling\n", "import pytest\n"],
        ids=["own package", "stdlib", "relative", "third party"],
    )
    def test_harmless_imports_pass(self, suite: SuiteBuilder, source: str) -> None:
        suite.plugin("alpha", files={"src/pkg_a/__init__.py": "", "src/pkg_a/mod.py": source})
        suite.plugin("beta", files=PKG_B)
        assert suite.build().problems() == []

    def test_unparsable_file_is_reported_not_fatal(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", files={"src/pkg_a/broken.py": "def (:\n"})
        problems = suite.build().problems()
        assert len(problems) == 1
        assert "cannot be parsed" in problems[0]

    def test_package_name_shared_by_two_plugins_is_reported(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", files=PKG_B).plugin("beta", files=PKG_B)
        assert suite.build().problems() == ["package pkg_b is defined by both alpha and beta"]

    def test_virtualenv_folders_are_skipped(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha", files={".venv/lib/vendored.py": "import pkg_b\n"})
        suite.plugin("beta", files=PKG_B)
        assert suite.build().problems() == []


class TestRealSuite:
    def test_this_repository_follows_its_own_rules(self) -> None:
        assert SuiteRules(REPO_ROOT).problems() == []


class TestCli:
    def test_clean_suite_exits_zero(self, suite: SuiteBuilder) -> None:
        suite.plugin("alpha")
        suite.build()
        assert repo_rules.main([str(suite.root)]) == 0

    def test_broken_suite_exits_one_and_explains(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.plugin("alpha").plugin("beta", listed=False)
        suite.build()
        assert repo_rules.main([str(suite.root)]) == 1
        assert "layout rule broken: plugins/beta is not listed" in capsys.readouterr().err

    def test_root_that_is_not_a_directory_exits_two(self, tmp_path: Path) -> None:
        assert repo_rules.main([str(tmp_path / "absent")]) == 2

    def test_constructor_rejects_a_file_as_root(self, tmp_path: Path) -> None:
        a_file = tmp_path / "file"
        a_file.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="not a directory"):
            SuiteRules(a_file)
