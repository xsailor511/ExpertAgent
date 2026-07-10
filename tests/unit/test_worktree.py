from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.teams.worktree import GitWorktree, valid_name


class TestValidName:
    def test_valid_simple(self):
        assert valid_name("feature-login")

    def test_valid_with_hyphen(self):
        assert valid_name("my-feature-branch")

    def test_valid_with_dot(self):
        assert valid_name("feature.v2")

    def test_invalid_with_slash(self):
        assert not valid_name("../escape")

    def test_invalid_empty(self):
        assert not valid_name("")

    def test_invalid_too_long(self):
        assert not valid_name("a" * 101)

    def test_invalid_path_traversal(self):
        assert not valid_name("..")

    def test_invalid_special_chars(self):
        assert not valid_name("feature with spaces")
        assert not valid_name("feature;rm")

    def test_invalid_dash_prefix(self):
        assert not valid_name("-flag")


class TestGitWorktree:
    def test_init_resolves_path(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        assert gt.repo_path == tmp_path.resolve()

    def test_create_validates_name(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        with pytest.raises(ValueError, match="Invalid worktree"):
            gt.create("../escape")

    def test_create_no_git_repo_raises(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        with pytest.raises(RuntimeError):
            gt.create("test-1")

    def test_exists_false_for_nonexistent(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        assert not gt.exists("nonexistent")

    def test_parse_porcelain_single(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        output = (
            "worktree /path/to/repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
        )
        result = gt._parse_porcelain(output)
        assert len(result) == 1
        assert result[0]["path"] == "/path/to/repo"
        assert result[0]["branch"] == "refs/heads/main"

    def test_parse_porcelain_multiple(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        output = (
            "worktree /main\n"
            "HEAD aaa\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /feature\n"
            "HEAD bbb\n"
            "branch refs/heads/wt/feature\n"
            "\n"
        )
        result = gt._parse_porcelain(output)
        assert len(result) == 2

    def test_parse_porcelain_empty(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        assert gt._parse_porcelain("") == []

    def test_parse_porcelain_detached(self, tmp_path: Path):
        gt = GitWorktree(tmp_path)
        output = (
            "worktree /detached\n"
            "HEAD ccc\n"
            "detached\n"
            "\n"
        )
        result = gt._parse_porcelain(output)
        assert len(result) == 1
        assert result[0].get("detached") is True
