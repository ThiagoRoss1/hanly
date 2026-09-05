"""The release decisions, exercised without touching a real release.

Every branch here is one the publisher takes on live repository state: which
commit a tag names, which build may be published under it, and whether an
existing release is a draft this run owns.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Sequence
from typing import Any

import pytest

from tools.release_build import (
    COMMIT_MARKER,
    GitHubAPI,
    ReleaseStateError,
    _next_page,
    classify_release,
    find_application_run,
    resolve_tag_commit,
    unique_semver_tag,
    verify_application_run,
    verify_published_assets,
)

REPOSITORY = "ThiagoRoss1/hanly"
TAG = "v0.1.0"
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


class _FakeAPI:
    """Answers the exact paths the resolver asks for, and nothing else."""

    def __init__(self, single: dict[str, Any], paged: dict[str, list[Any]] | None = None) -> None:
        self.single = single
        self.paged = paged or {}

    def get(self, path: str, **parameters: str) -> Any:
        del parameters
        if path not in self.single:
            raise AssertionError(f"unexpected request for {path}")
        return self.single[path]

    def get_all(self, path: str, **parameters: str) -> list[Any]:
        del parameters
        return self.paged.get(path, [])


def _reference(object_type: str, sha: str) -> dict[str, Any]:
    return {"object": {"type": object_type, "sha": sha}}


def _run(**overrides: Any) -> dict[str, Any]:
    run = {
        "id": 33929041113,
        "path": ".github/workflows/build.yml@refs/tags/v0.1.0",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "head_sha": COMMIT,
        "head_branch": TAG,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-09-04T23:19:10Z",
    }
    run.update(overrides)
    return run


def _draft(commit: str = COMMIT, **overrides: Any) -> dict[str, Any]:
    release = {
        "draft": True,
        "prerelease": False,
        "body": f"Hanly Desktop {TAG}\n\n{COMMIT_MARKER} {commit}\n",
    }
    release.update(overrides)
    return release


def test_a_lightweight_tag_resolves_straight_to_its_commit() -> None:
    api = _FakeAPI({f"repos/{REPOSITORY}/git/ref/tags/{TAG}": _reference("commit", COMMIT)})

    assert resolve_tag_commit(api, REPOSITORY, TAG) == COMMIT


def test_an_annotated_tag_is_peeled_until_it_names_a_commit() -> None:
    annotation = "c" * 40
    api = _FakeAPI(
        {
            f"repos/{REPOSITORY}/git/ref/tags/{TAG}": _reference("tag", annotation),
            f"repos/{REPOSITORY}/git/tags/{annotation}": _reference("commit", COMMIT),
        }
    )

    assert resolve_tag_commit(api, REPOSITORY, TAG) == COMMIT


def test_a_tag_that_never_reaches_a_commit_is_refused() -> None:
    """A cycle would otherwise spin; the depth cap turns it into an error."""

    annotation = "c" * 40
    api = _FakeAPI(
        {
            f"repos/{REPOSITORY}/git/ref/tags/{TAG}": _reference("tag", annotation),
            f"repos/{REPOSITORY}/git/tags/{annotation}": _reference("tag", annotation),
        }
    )

    with pytest.raises(ReleaseStateError, match="too deep"):
        resolve_tag_commit(api, REPOSITORY, TAG)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0-rc1", "latest"])
def test_only_a_plain_semver_tag_is_a_release_tag(tag: str) -> None:
    with pytest.raises(ReleaseStateError, match="vMAJOR"):
        resolve_tag_commit(_FakeAPI({}), REPOSITORY, tag)


def test_two_semver_tags_on_one_commit_are_ambiguous() -> None:
    """Publishing would have to guess which tag the release belongs to."""

    api = _FakeAPI(
        {},
        {
            f"repos/{REPOSITORY}/git/refs/tags": [
                {"ref": "refs/tags/v0.1.0", **_reference("commit", COMMIT)},
                {"ref": "refs/tags/v0.2.0", **_reference("commit", COMMIT)},
                {"ref": "refs/tags/nightly", **_reference("commit", COMMIT)},
            ]
        },
    )

    with pytest.raises(ReleaseStateError, match="exactly one semver tag"):
        unique_semver_tag(api, REPOSITORY, COMMIT)


def test_the_one_semver_tag_naming_the_commit_is_returned() -> None:
    api = _FakeAPI(
        {},
        {
            f"repos/{REPOSITORY}/git/refs/tags": [
                {"ref": "refs/tags/v0.1.0", **_reference("commit", COMMIT)},
                {"ref": "refs/tags/v0.2.0", **_reference("commit", OTHER_COMMIT)},
            ]
        },
    )

    assert unique_semver_tag(api, REPOSITORY, COMMIT) == TAG


def test_a_matching_build_run_is_accepted_with_its_id() -> None:
    run_id = verify_application_run(_run(), repository=REPOSITORY, tag=TAG, commit=COMMIT)

    assert run_id == 33929041113


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"path": ".github/workflows/release.yml"}, "is not .github/workflows/build.yml"),
        ({"repository": {"full_name": "someone/else"}}, "another repository"),
        ({"head_repository": {"full_name": "someone/else"}}, "head repository"),
        ({"head_sha": OTHER_COMMIT}, "head_sha is not the tag commit"),
        ({"head_branch": "main"}, "head_branch is not the release tag"),
        ({"event": "workflow_dispatch"}, "not triggered by a push"),
        ({"status": "in_progress"}, "not completed"),
        ({"conclusion": "failure"}, "did not succeed"),
        ({"id": "33929041113"}, "no numeric id"),
    ],
)
def test_a_build_run_that_is_not_the_tags_own_is_refused(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ReleaseStateError, match=message):
        verify_application_run(_run(**overrides), repository=REPOSITORY, tag=TAG, commit=COMMIT)


def test_the_newest_matching_push_build_is_the_one_a_recovery_publishes() -> None:
    api = _FakeAPI(
        {},
        {
            f"repos/{REPOSITORY}/actions/workflows/build.yml/runs": [
                {
                    "workflow_runs": [
                        _run(id=1, created_at="2026-09-01T00:00:00Z"),
                        _run(id=2, created_at="2026-09-04T23:19:10Z"),
                        _run(id=3, head_sha=OTHER_COMMIT),
                    ]
                }
            ]
        },
    )

    assert find_application_run(api, repository=REPOSITORY, tag=TAG, commit=COMMIT) == 2


def test_no_build_for_the_exact_commit_is_refused_rather_than_approximated() -> None:
    api = _FakeAPI(
        {},
        {
            f"repos/{REPOSITORY}/actions/workflows/build.yml/runs": [
                {"workflow_runs": [_run(head_sha=OTHER_COMMIT)]}
            ]
        },
    )

    with pytest.raises(ReleaseStateError, match="no successful push build"):
        find_application_run(api, repository=REPOSITORY, tag=TAG, commit=COMMIT)


def test_an_unheld_tag_is_staged_from_scratch() -> None:
    decision = classify_release(None, commit=COMMIT, event="workflow_run")

    assert decision.action == "create"


def test_the_draft_staged_for_this_commit_is_reused_not_treated_as_a_collision() -> None:
    """Re-running a recovery has to repair its own draft rather than refuse it."""

    decision = classify_release(_draft(), commit=COMMIT, event="workflow_dispatch")

    assert decision.action == "reuse"


@pytest.mark.parametrize(
    "release",
    [
        _draft(OTHER_COMMIT),
        _draft(body="a draft someone else opened"),
        _draft(body=""),
    ],
)
def test_a_draft_that_is_not_this_commits_draft_is_refused(release: dict[str, Any]) -> None:
    with pytest.raises(ReleaseStateError, match="unrelated draft"):
        classify_release(release, commit=COMMIT, event="workflow_dispatch")


def test_a_prerelease_holding_the_tag_is_never_overwritten() -> None:
    with pytest.raises(ReleaseStateError, match="prerelease"):
        classify_release(
            _draft(draft=False, prerelease=True), commit=COMMIT, event="workflow_run"
        )


def test_manual_recovery_refuses_a_tag_that_is_already_public() -> None:
    with pytest.raises(ReleaseStateError, match="existing public release"):
        classify_release(_draft(draft=False), commit=COMMIT, event="workflow_dispatch")


RESOURCE_ASSET_NAME = "krdict-20260819-v1.sqlite3.zst"
PUBLISHED_ASSETS = (
    "hanly-desktop-windows.zip",
    "hanly-desktop-macos.tar.gz",
    "hanly-desktop-linux.tar.gz",
    RESOURCE_ASSET_NAME,
    "hanly-resources.json",
    "SHA256SUMS",
)


def _published(assets: Sequence[str] = PUBLISHED_ASSETS, commit: str = COMMIT) -> dict[str, Any]:
    return _draft(commit, draft=False, assets=[{"name": name} for name in assets])


def test_a_complete_public_release_for_this_commit_is_a_no_op() -> None:
    """Only a finished release of this lane's own is safe to stay silent about."""

    decision = classify_release(_published(), commit=COMMIT, event="workflow_run")

    assert decision.action == "noop"


def test_a_public_release_for_another_commit_is_a_collision_not_a_no_op() -> None:
    with pytest.raises(ReleaseStateError, match="not published for this commit"):
        classify_release(_published(commit=OTHER_COMMIT), commit=COMMIT, event="workflow_run")


def test_a_public_release_this_lane_did_not_publish_is_refused() -> None:
    foreign = _published()
    foreign["body"] = "someone published this by hand"

    with pytest.raises(ReleaseStateError, match="not published for this commit"):
        classify_release(foreign, commit=COMMIT, event="workflow_run")


@pytest.mark.parametrize(
    ("assets", "message"),
    [
        (PUBLISHED_ASSETS[:-1], "not the exact six"),
        (PUBLISHED_ASSETS + ("krdict-other.sqlite3.zst",), "exactly one KRDICT asset"),
        (
            tuple(name for name in PUBLISHED_ASSETS if name != RESOURCE_ASSET_NAME),
            "exactly one KRDICT",
        ),
        (PUBLISHED_ASSETS + ("hanly-desktop-windows.zip",), "duplicate asset name"),
        (PUBLISHED_ASSETS + ("krdict.sqlite3",), "not the exact six"),
    ],
)
def test_a_partial_or_inconsistent_public_release_fails_rather_than_no_ops(
    assets: Sequence[str], message: str
) -> None:
    """A half-finished release must be repaired deliberately, not passed over."""

    with pytest.raises(ReleaseStateError, match=message):
        classify_release(_published(assets), commit=COMMIT, event="workflow_run")


def test_a_release_payload_without_an_asset_list_is_refused() -> None:
    published = _draft(draft=False)

    with pytest.raises(ReleaseStateError, match="no asset list"):
        classify_release(published, commit=COMMIT, event="workflow_run")


def test_the_exact_six_asset_names_are_what_a_release_is() -> None:
    assert verify_published_assets(list(PUBLISHED_ASSETS)) == RESOURCE_ASSET_NAME


# --- Pagination ---------------------------------------------------------------


class _Response:
    """The slice of an ``http.client`` response ``GitHubAPI`` reads."""

    def __init__(self, body: Any, link: str | None) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"Link": link} if link else {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exception: object) -> None:
        return None


def _paged_opener(pages: dict[str, Any], seen: list[str]):
    def opener(request: Any, timeout: int = 0) -> _Response:
        del timeout
        url = request.full_url
        seen.append(url)
        body, link = pages[url]
        return _Response(body, link)

    return opener


def test_pagination_follows_the_link_header_until_it_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three pages of tags arrive as one flat list, in order."""

    first = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100"
    second = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100&page=2"
    third = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100&page=3"
    pages = {
        first: ([{"ref": "one"}], f'<{second}>; rel="next", <{third}>; rel="last"'),
        second: ([{"ref": "two"}], f'<{third}>; rel="next"'),
        third: ([{"ref": "three"}], None),
    }
    seen: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _paged_opener(pages, seen))

    collected = GitHubAPI("token").get_all("repos/o/r/git/refs/tags")

    assert [entry["ref"] for entry in collected] == ["one", "two", "three"]
    assert seen == [first, second, third]


def test_pagination_keeps_an_object_page_whole_rather_than_flattening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runs endpoint answers with an object per page, not a list."""

    first = "https://api.github.com/repos/o/r/runs?event=push&per_page=100"
    second = "https://api.github.com/repos/o/r/runs?event=push&per_page=100&page=2"
    pages = {
        first: ({"workflow_runs": [{"id": 1}]}, f'<{second}>; rel="next"'),
        second: ({"workflow_runs": [{"id": 2}]}, None),
    }
    seen: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _paged_opener(pages, seen))

    collected = GitHubAPI("token").get_all("repos/o/r/runs", event="push")

    assert [page["workflow_runs"][0]["id"] for page in collected] == [1, 2]
    assert len(seen) == 2


def test_a_single_page_is_one_request_and_no_link_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100"
    seen: list[str] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", _paged_opener({url: ([{"ref": "only"}], None)}, seen)
    )

    assert GitHubAPI("token").get_all("repos/o/r/git/refs/tags") == [{"ref": "only"}]
    assert seen == [url]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ('<https://x/2>; rel="last"', None),
        ('<https://x/2>; rel="next"', "https://x/2"),
        ('<https://x/2>; rel="next", <https://x/9>; rel="last"', "https://x/2"),
        ('<https://x/9>; rel="last", <https://x/2>; rel="next"', "https://x/2"),
    ],
)
def test_only_the_next_link_continues_a_listing(header: str | None, expected: str | None) -> None:
    assert _next_page(header) == expected


def test_a_paginated_tag_listing_reaches_the_semver_tag_on_a_later_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver's own listing has to survive a repository with many tags."""

    first = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100"
    second = "https://api.github.com/repos/o/r/git/refs/tags?per_page=100&page=2"
    pages = {
        first: (
            [{"ref": "refs/tags/nightly", **_reference("commit", COMMIT)}],
            f'<{second}>; rel="next"',
        ),
        second: ([{"ref": "refs/tags/v0.1.0", **_reference("commit", COMMIT)}], None),
    }
    monkeypatch.setattr(urllib.request, "urlopen", _paged_opener(pages, []))

    assert unique_semver_tag(GitHubAPI("token"), "o/r", COMMIT) == TAG
