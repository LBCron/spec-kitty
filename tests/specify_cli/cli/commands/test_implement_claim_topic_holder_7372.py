"""#7372 / FR-061: the claim commit runs in the checkout holding a default Mission's topic branch.

Until a ``topology_source: default`` Mission lands, the PRIMARY write home of
``WORK_PACKAGE_TASK`` is its topic branch, held by the coordination worktree, while the
repository root checkout is back on ``create_return_branch``. The #5738 up-front HEAD check
and the claim commit must both judge that holder, never the repository root checkout.
The seam and the status read are stubbed; the checkouts are a real git repository.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from specify_cli.cli.commands import implement_claim
from specify_cli.git.commit_helpers import SafeCommitHeadMismatch
from tests._support.git_cli import git_out

pytestmark = [pytest.mark.unit, pytest.mark.git_repo]

_SLUG = "probe-01M6XCQ7"
_TOPIC = "kitty/mission-probe-01M6XCQ7"


@pytest.fixture()
def repo_with_topic_holder(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git_out(repo, "init", "-q", "-b", "work")
    git_out(repo, "config", "user.email", "t@example.com")
    git_out(repo, "config", "user.name", "Test")
    git_out(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    git_out(repo, "add", "-A")
    git_out(repo, "commit", "-qm", "init")
    holder = repo / ".worktrees" / f"{_SLUG}-coord"
    git_out(repo, "worktree", "add", "-q", "-b", _TOPIC, str(holder))
    (holder / "kitty-specs" / _SLUG).mkdir(parents=True)
    return repo, holder


@pytest.fixture()
def planned_wp_on_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """The WP is ``planned`` and the seam's PRIMARY write target is the topic branch."""
    import specify_cli.status as status_pkg

    monkeypatch.setattr(status_pkg, "resolve_status_read", lambda *_a, **_k: object())
    monkeypatch.setattr(status_pkg, "materialize_status", lambda *_a, **_k: SimpleNamespace(work_packages={"WP01": {"lane": "planned"}}))
    seam = SimpleNamespace(write_target=lambda _kind: SimpleNamespace(ref=_TOPIC))
    monkeypatch.setattr(implement_claim, "placement_seam", lambda *_a, **_k: seam)


@pytest.mark.usefixtures("planned_wp_on_topic")
def test_head_check_judges_the_topic_holder_not_the_repository_root(repo_with_topic_holder: tuple[Path, Path]) -> None:
    repo, holder = repo_with_topic_holder
    implement_claim._raise_if_claim_commit_head_mismatch(repo, _SLUG, "WP01", True, holder / "kitty-specs" / _SLUG)


@pytest.mark.usefixtures("planned_wp_on_topic")
def test_head_check_without_the_mission_dir_keeps_judging_the_repository_root(repo_with_topic_holder: tuple[Path, Path]) -> None:
    """The pre-#7372 call shape still refuses: the repository root checkout is on ``work``."""
    repo, _holder = repo_with_topic_holder
    with pytest.raises(SafeCommitHeadMismatch) as excinfo:
        implement_claim._raise_if_claim_commit_head_mismatch(repo, _SLUG, "WP01", True)
    assert "HEAD is 'work'" in str(excinfo.value)


@pytest.mark.usefixtures("planned_wp_on_topic")
def test_head_check_with_a_mission_dir_outside_the_holder_judges_the_repository_root(repo_with_topic_holder: tuple[Path, Path]) -> None:
    repo, _holder = repo_with_topic_holder
    with pytest.raises(SafeCommitHeadMismatch):
        implement_claim._raise_if_claim_commit_head_mismatch(repo, _SLUG, "WP01", True, repo / "kitty-specs" / _SLUG)


def test_claim_commit_checkout_is_the_topic_holder(repo_with_topic_holder: tuple[Path, Path]) -> None:
    repo, holder = repo_with_topic_holder
    assert implement_claim._claim_commit_checkout(repo, holder / "kitty-specs" / _SLUG, _TOPIC).resolve() == holder.resolve()
    assert implement_claim._claim_commit_checkout(repo, repo / "kitty-specs" / _SLUG, "work") == repo


def test_claim_commit_target_is_none_when_the_seam_cannot_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    from mission_runtime import ActionContextError

    def _unresolvable(*_a: object, **_k: object) -> object:
        raise ActionContextError("NO_CONTEXT", "no context")

    monkeypatch.setattr(implement_claim, "placement_seam", _unresolvable)
    assert implement_claim._claim_commit_target(Path("."), _SLUG) is None


def test_no_auto_commit_stages_the_claim_writes_in_the_topic_holder(repo_with_topic_holder: tuple[Path, Path]) -> None:
    """``--no-auto-commit`` stages in the holder, never a ``.worktrees/`` path in the repository root index."""
    repo, holder = repo_with_topic_holder
    meta = holder / "kitty-specs" / _SLUG / "meta.json"
    meta.write_text("{}\n", encoding="utf-8")
    implement_claim._stage_claim_writes(holder, "WP01", lambda: [meta])
    assert git_out(holder, "diff", "--cached", "--name-only").strip() == f"kitty-specs/{_SLUG}/meta.json"
    assert git_out(repo, "diff", "--cached", "--name-only").strip() == ""
