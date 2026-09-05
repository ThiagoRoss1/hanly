"""Resolve and classify the GitHub state one Hanly release depends on.

The release workflow asks these questions twice: once to stage a draft, and
once behind a protected environment to publish it. Both halves need the same
answers -- which commit the tag names, which successful build produced its
artifacts, and whether an existing release is a draft this run may reuse -- so
the decisions live here, where they can be exercised without a real release.

Every answer is derived from the tag and the build that produced the artifacts.
Nothing here creates, moves, or deletes anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

API_ROOT = "https://api.github.com"
APPLICATION_WORKFLOW = ".github/workflows/build.yml"

#: Written into the draft body at stage time and required at finalize time. A
#: draft without it is not this workflow's draft, whatever its tag says.
COMMIT_MARKER = "Hanly-Release-Commit:"

#: What a finished Hanly release holds, beside its one KRDICT resource.
FIXED_RELEASE_ASSETS = frozenset(
    {
        "hanly-desktop-windows.zip",
        "hanly-desktop-macos.tar.gz",
        "hanly-desktop-linux.tar.gz",
        "hanly-resources.json",
        "SHA256SUMS",
    }
)
RESOURCE_ASSET = re.compile(r"^krdict-[A-Za-z0-9._-]+\.sqlite3\.zst$")

SEMVER_TAG = re.compile(r"^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

#: An annotated tag may point at another tag. The chain is finite in practice,
#: and a cap turns a malicious cycle into an error rather than a hang.
MAX_TAG_DEPTH = 16


class ReleaseStateError(RuntimeError):
    """Raised when the release state is not what the tag and build require."""


@dataclass(frozen=True)
class ApplicationBuild:
    """The one successful build whose artifacts a release may publish."""

    head_sha: str
    run_id: int


@dataclass(frozen=True)
class ReleaseDecision:
    """What the stage job should do about the release that already exists."""

    action: str
    reason: str


class ReadOnlyAPI(Protocol):
    """The read-only slice of the REST API these decisions need.

    A protocol rather than the concrete client: the resolution rules are the
    part worth testing, and they should not need a network to be exercised.
    """

    def get(self, path: str, **parameters: str) -> Any: ...

    def get_all(self, path: str, **parameters: str) -> list[Any]: ...


class GitHubAPI:
    """Reads that slice from api.github.com."""

    def __init__(self, token: str, *, root: str = API_ROOT) -> None:
        self._token = token
        self._root = root

    def get(self, path: str, **parameters: str) -> Any:
        return self._request(self._url(path, parameters))

    def get_all(self, path: str, **parameters: str) -> list[Any]:
        """Follow ``Link`` pagination and concatenate every page."""

        url: str | None = self._url(path, {**parameters, "per_page": "100"})
        collected: list[Any] = []
        while url is not None:
            payload, url = self._request(url, with_next=True)
            collected.extend(payload if isinstance(payload, list) else [payload])
        return collected

    def _url(self, path: str, parameters: Mapping[str, str]) -> str:
        url = f"{self._root}/{path.lstrip('/')}"
        if parameters:
            url = f"{url}?{urllib.parse.urlencode(parameters)}"
        return url

    def _request(self, url: str, *, with_next: bool = False) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "hanly-release",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not with_next:
                return payload
            return payload, _next_page(response.headers.get("Link"))


def _next_page(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        target, _, relation = part.partition(";")
        if 'rel="next"' in relation:
            return target.strip().strip("<>")
    return None


def resolve_tag_commit(api: ReadOnlyAPI, repository: str, tag: str) -> str:
    """Peel ``tag`` down to the commit it names."""

    if not RELEASE_TAG.fullmatch(tag):
        raise ReleaseStateError(f"release tag {tag!r} must be vMAJOR.MINOR.PATCH")

    reference = api.get(f"repos/{repository}/git/ref/tags/{tag}")
    return _peel(api, repository, reference.get("object", {}), f"release tag {tag}")


def _peel(api: ReadOnlyAPI, repository: str, obj: Mapping[str, Any], label: str) -> str:
    object_type = obj.get("type")
    object_sha = obj.get("sha")

    for _ in range(MAX_TAG_DEPTH):
        if object_type != "tag":
            break
        if not isinstance(object_sha, str) or not COMMIT_SHA.fullmatch(object_sha):
            raise ReleaseStateError(f"{label} annotation object is not a SHA")
        annotated = api.get(f"repos/{repository}/git/tags/{object_sha}").get("object", {})
        object_type = annotated.get("type")
        object_sha = annotated.get("sha")
    else:
        raise ReleaseStateError(f"{label} annotation chain is too deep")

    if object_type != "commit":
        raise ReleaseStateError(f"{label} did not resolve to a commit object")
    if not isinstance(object_sha, str) or not COMMIT_SHA.fullmatch(object_sha):
        raise ReleaseStateError(f"{label} did not resolve to a commit SHA")
    return object_sha


def unique_semver_tag(api: ReadOnlyAPI, repository: str, commit: str) -> str:
    """Return the one semver tag naming ``commit``, refusing any ambiguity."""

    naming = []
    for reference in api.get_all(f"repos/{repository}/git/refs/tags"):
        ref = reference.get("ref", "")
        if not SEMVER_TAG.fullmatch(ref):
            continue
        name = ref.removeprefix("refs/tags/")
        if _peel(api, repository, reference.get("object", {}), f"tag {name}") == commit:
            naming.append(name)

    if len(naming) != 1:
        raise ReleaseStateError("expected exactly one semver tag for the release commit")
    return naming[0]


def verify_application_run(
    run: Mapping[str, Any], *, repository: str, tag: str, commit: str
) -> int:
    """Return the run id, once the run is provably the tag's own build."""

    path = str(run.get("path") or "").split("@", 1)[0]
    checks = (
        (path == APPLICATION_WORKFLOW, f"application run is not {APPLICATION_WORKFLOW}"),
        (
            _full_name(run.get("repository")) == repository,
            "application run belongs to another repository",
        ),
        (
            _full_name(run.get("head_repository")) == repository,
            "application head repository belongs to another repository",
        ),
        (run.get("head_sha") == commit, "application run head_sha is not the tag commit"),
        (run.get("head_branch") == tag, "application run head_branch is not the release tag"),
        (run.get("event") == "push", "application run was not triggered by a push"),
        (run.get("status") == "completed", "application run is not completed"),
        (run.get("conclusion") == "success", "application run did not succeed"),
    )
    for satisfied, message in checks:
        if not satisfied:
            raise ReleaseStateError(message)

    run_id = run.get("id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ReleaseStateError("application run has no numeric id")
    return run_id


def _full_name(value: Any) -> str | None:
    return value.get("full_name") if isinstance(value, Mapping) else None


def find_application_run(
    api: ReadOnlyAPI, *, repository: str, tag: str, commit: str
) -> int:
    """Return the newest successful push build for the exact tag commit."""

    runs = api.get_all(
        f"repos/{repository}/actions/workflows/build.yml/runs",
        event="push",
        status="completed",
    )
    candidates = [
        run
        for page in runs
        for run in (page.get("workflow_runs", []) if isinstance(page, Mapping) else [])
        if run.get("head_sha") == commit and run.get("head_branch") == tag
    ]
    if not candidates:
        raise ReleaseStateError("no successful push build for the exact tag commit")

    newest = max(candidates, key=lambda run: str(run.get("created_at") or ""))
    return verify_application_run(newest, repository=repository, tag=tag, commit=commit)


def verify_published_assets(names: Sequence[str]) -> str:
    """Return the resource asset name, once ``names`` is exactly a release set.

    A partial or foreign public release must not be mistaken for a finished one,
    so the six names are checked rather than counted.
    """

    unique = set(names)
    if len(unique) != len(names):
        raise ReleaseStateError("the published release lists a duplicate asset name")

    resources = sorted(name for name in unique if RESOURCE_ASSET.fullmatch(name))
    if len(resources) != 1:
        raise ReleaseStateError(
            f"the published release must hold exactly one KRDICT asset; found {len(resources)}"
        )
    if unique - {resources[0]} != FIXED_RELEASE_ASSETS:
        missing = sorted(FIXED_RELEASE_ASSETS - unique)
        unexpected = sorted(unique - FIXED_RELEASE_ASSETS - {resources[0]})
        raise ReleaseStateError(
            f"the published release is not the exact six assets; missing {missing}, "
            f"unexpected {unexpected}"
        )
    return resources[0]


def _asset_names(release: Mapping[str, Any]) -> list[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseStateError("the release payload carries no asset list")
    return [asset.get("name", "") for asset in assets if isinstance(asset, Mapping)]


def classify_release(
    release: Mapping[str, Any] | None, *, commit: str, event: str
) -> ReleaseDecision:
    """Decide what an existing release for this tag means for the stage job.

    A draft this workflow staged for this exact commit is not a collision: a
    rerun repairs it. Anything else that already occupies the tag is, except an
    automatic rerun of a tag this lane has already published in full.
    """

    if release is None:
        return ReleaseDecision("create", "no release exists for the tag")

    if release.get("prerelease"):
        raise ReleaseStateError("a prerelease already occupies the tag; refusing to overwrite")

    body = release.get("body") or ""
    staged_here = f"{COMMIT_MARKER} {commit}" in body

    if not release.get("draft"):
        if event != "workflow_run":
            raise ReleaseStateError("manual recovery refuses an existing public release")
        # Silence is only safe once the public release is provably this lane's
        # finished work for this commit. Anything else is a collision.
        if not staged_here:
            raise ReleaseStateError(
                "a public release holds the tag but was not published for this commit"
            )
        verify_published_assets(_asset_names(release))
        return ReleaseDecision("noop", "the tag is already published in full; successful no-op")

    if not staged_here:
        raise ReleaseStateError(
            "an unrelated draft occupies the tag, or its draft names another commit"
        )
    return ReleaseDecision("reuse", "reusing the draft staged for this commit")


def _resolve(
    api: ReadOnlyAPI, repository: str, tag: str, run_id: str | None
) -> ApplicationBuild:
    commit = resolve_tag_commit(api, repository, tag)
    if unique_semver_tag(api, repository, commit) != tag:
        raise ReleaseStateError("the resolved semver tag is not the requested release tag")

    if run_id is None:
        resolved = find_application_run(api, repository=repository, tag=tag, commit=commit)
    else:
        # A `workflow_run` trigger already names its build. Verifying that one
        # keeps the release tied to the run that fired it, rather than to
        # whichever matching run happens to be newest.
        if not run_id.isdigit():
            raise ReleaseStateError("application run id is not numeric")
        resolved = verify_application_run(
            api.get(f"repos/{repository}/actions/runs/{run_id}"),
            repository=repository,
            tag=tag,
            commit=commit,
        )
    return ApplicationBuild(commit, resolved)


def _api(token: str | None) -> GitHubAPI:
    if not token:
        raise ReleaseStateError("GH_TOKEN is required")
    return GitHubAPI(token)


def _release_for_tag(
    api: ReadOnlyAPI, repository: str, tag: str
) -> Mapping[str, Any] | None:
    releases = [
        release
        for release in api.get_all(f"repos/{repository}/releases")
        if isinstance(release, Mapping) and release.get("tag_name") == tag
    ]
    if len(releases) > 1:
        raise ReleaseStateError("multiple releases occupy the tag; remove obsolete drafts")
    return releases[0] if releases else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["resolve", "classify"])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--event", default="workflow_dispatch")
    parser.add_argument("--commit", default=None, help="classify mode: the resolved tag commit")
    parser.add_argument(
        "--run-id",
        default=None,
        help="resolve mode: verify this exact build run instead of searching for one",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print ``name=value`` lines the workflow appends to ``GITHUB_OUTPUT``."""

    args = _parser().parse_args(argv)
    try:
        api = _api(os.environ.get("GH_TOKEN"))
        if args.mode == "resolve":
            build = _resolve(api, args.repository, args.tag, args.run_id)
            print(f"head_sha={build.head_sha}")
            print(f"run_id={build.run_id}")
            return 0

        if not args.commit:
            raise ReleaseStateError("classify mode requires --commit")
        release = _release_for_tag(api, args.repository, args.tag)
        release_id = ""
        if release is not None:
            raw_release_id = release.get("id")
            if (
                not isinstance(raw_release_id, int)
                or isinstance(raw_release_id, bool)
                or raw_release_id <= 0
            ):
                raise ReleaseStateError("the release payload has no valid numeric id")
            release_id = str(raw_release_id)
        decision = classify_release(release, commit=args.commit, event=args.event)
        print(f"action={decision.action}")
        print(f"reason={decision.reason}")
        print(f"release_id={release_id}")
    except ReleaseStateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APPLICATION_WORKFLOW",
    "FIXED_RELEASE_ASSETS",
    "ReadOnlyAPI",
    "COMMIT_MARKER",
    "ApplicationBuild",
    "GitHubAPI",
    "ReleaseDecision",
    "ReleaseStateError",
    "classify_release",
    "find_application_run",
    "main",
    "resolve_tag_commit",
    "unique_semver_tag",
    "verify_application_run",
    "verify_published_assets",
]
