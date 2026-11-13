"""Scratch worktrees: warm cache by hardlinks, safe fallbacks, and the real reimport behaviour."""

from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_OK, EXIT_REFUSED
from godotkit.runner import GodotRunner
from godotkit.worktree import CacheWarmer, GitError, WorktreeManager
from godotkit_rig import GIT_ENV, CliRunner, FakeGodotFactory, write_png


def _seed_cache(project: Path) -> None:
    (project / ".godot" / "imported").mkdir(parents=True)
    (project / ".godot" / "imported" / "icon.ctex").write_bytes(b"x" * 100)
    (project / ".godot" / "editor").mkdir()
    (project / ".godot" / "editor" / "filesystem_cache10").write_text("cache")


def _commit_all(project: Path) -> None:
    for args in (["add", "-A"], ["commit", "-q", "-m", "more"]):
        subprocess.run(["git", "-C", str(project), *args], check=True, env=GIT_ENV)


class TestWarmWorktree:
    def test_imported_files_are_linked_and_the_rest_copied(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        _seed_cache(git_project)
        report = WorktreeManager().create(git_project, tmp_path / "wt", "HEAD", None)
        cache = tmp_path / "wt" / ".godot"
        source = git_project / ".godot"
        assert report.cache is not None
        assert (report.cache.linked_files, report.cache.copied_files) == (1, 1)
        linked = cache / "imported" / "icon.ctex"
        assert linked.stat().st_ino == (source / "imported" / "icon.ctex").stat().st_ino
        copied = cache / "editor" / "filesystem_cache10"
        assert copied.stat().st_ino != (source / "editor" / "filesystem_cache10").stat().st_ino

    def test_without_a_cache_the_worktree_starts_cold(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        report = WorktreeManager().create(git_project, tmp_path / "wt", "HEAD", None)
        assert report.cache is None
        assert (tmp_path / "wt" / "project.godot").is_file()

    def test_project_below_the_repo_top_keeps_its_offset(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        project = repo / "game"
        project.mkdir(parents=True)
        (project / "project.godot").write_text("config_version=5\n")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        _commit_all(repo)
        _seed_cache(project)
        WorktreeManager().create(project, tmp_path / "wt", "HEAD", None)
        assert (tmp_path / "wt" / "game" / ".godot" / "imported" / "icon.ctex").is_file()

    def test_existing_path_is_refused(self, git_project: Path, tmp_path: Path) -> None:
        (tmp_path / "wt").mkdir()
        with pytest.raises(ValueError, match="already exists"):
            WorktreeManager().create(git_project, tmp_path / "wt", "HEAD", None)

    def test_unknown_ref_is_a_git_error(self, git_project: Path, tmp_path: Path) -> None:
        with pytest.raises(GitError, match="worktree add"):
            WorktreeManager().create(git_project, tmp_path / "wt", "no-such-ref", None)

    def test_remove_deletes_worktree_and_cache(self, git_project: Path, tmp_path: Path) -> None:
        _seed_cache(git_project)
        manager = WorktreeManager()
        manager.create(git_project, tmp_path / "wt", "HEAD", None)
        manager.remove(tmp_path / "wt")
        assert not (tmp_path / "wt").exists()
        assert (git_project / ".godot" / "imported" / "icon.ctex").is_file()

    def test_remove_refuses_the_main_checkout(self, git_project: Path) -> None:
        with pytest.raises(ValueError, match="not a linked git worktree"):
            WorktreeManager().remove(git_project)


class TestCacheWarmer:
    def test_cross_device_link_falls_back_to_copy(self, git_project: Path, tmp_path: Path) -> None:
        _seed_cache(git_project)

        def cross_device(_: Path, __: Path) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        report = CacheWarmer(cross_device).warm(git_project / ".godot", tmp_path / "cache")
        assert (report.linked_files, report.copied_files) == (0, 2)
        assert (tmp_path / "cache" / "imported" / "icon.ctex").read_bytes() == b"x" * 100

    def test_other_link_errors_propagate(self, git_project: Path, tmp_path: Path) -> None:
        _seed_cache(git_project)

        def no_space(_: Path, __: Path) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        with pytest.raises(OSError, match="No space"):
            CacheWarmer(no_space).warm(git_project / ".godot", tmp_path / "cache")


@pytest.mark.live_godot
class TestRealReimport:
    def test_reimport_in_a_worktree_leaves_the_shared_cache_alone(
        self, real_godot: GodotBinary, git_project: Path, tmp_path: Path
    ) -> None:
        write_png(git_project / "icon.png", (255, 0, 0))
        importer = ProjectImporter(GodotRunner(real_godot))
        assert importer.run(ImportRequest(git_project, timeout_s=120)).verdict.ok
        _commit_all(git_project)
        source = next((git_project / ".godot" / "imported").glob("icon.png-*.ctex"))
        before = (source.stat().st_ino, source.read_bytes())

        worktree = tmp_path / "wt"
        WorktreeManager().create(git_project, worktree, "HEAD", None)
        write_png(worktree / "icon.png", (0, 0, 255))
        report = importer.run(ImportRequest(worktree, timeout_s=120))

        assert report.verdict.ok
        assert not report.cold
        assert (source.stat().st_ino, source.read_bytes()) == before
        assert (worktree / ".godot" / "imported" / source.name).read_bytes() != before[1]


class TestWorktreeCli:
    def test_new_then_remove(
        self, git_project: Path, tmp_path: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        _seed_cache(git_project)
        path = str(tmp_path / "wt")
        code, payload = run_cli(
            ["worktree", "new", path, "--project", str(git_project)], fake_godot()
        )
        assert code == EXIT_OK
        assert payload["cache"] == {
            "linked_files": 1,
            "copied_files": 1,
            "linked_bytes": 100,
            "copied_bytes": 5,
        }
        code, payload = run_cli(["worktree", "remove", path], fake_godot())
        assert (code, payload["ok"]) == (EXIT_OK, True)

    def test_remove_of_a_plain_folder_is_refused(
        self, tmp_path: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        code, payload = run_cli(["worktree", "remove", str(tmp_path)], fake_godot())
        assert (code, payload["reason"]) == (EXIT_REFUSED, "refused")
