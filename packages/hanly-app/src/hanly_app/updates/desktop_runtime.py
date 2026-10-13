"""Compose desktop updates without importing a UI framework.

The native shell and Python service share the same verified updater. This
module supplies the app-specific release configuration and staging strategy;
it deliberately owns no window, event loop, or acknowledgement policy.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from hanly.resource_manager import ResourceManager

from hanly_app.first_run import persist_installed_resource
from hanly_app.updates.build_identity import (
    BuildStamp,
    ReceiptStore,
    read_build_stamp,
    receipt_store,
)
from hanly_app.updates.coordinator import ApplicationInstall, UpdateCoordinator
from hanly_app.updates.desktop_update import (
    APPLICATION_STEM,
    ApplicationInstaller,
    ApplicationUpdate,
    ApplicationUpdateError,
    check_application_update,
    confirm_started,
    confirm_started_v2,
    installation_root,
)
from hanly_app.updates.installer import (
    DifferentialUpdateError,
    PosixTreeStaging,
    TreeUpdateInstaller,
    WindowsFileStaging,
)
from hanly_app.updates.manifest import PLATFORM_WINDOWS
from hanly_app.updates.resource_service import (
    GitHubReleaseFetcher,
    ProgressCallback,
    UpdateService,
)
from hanly_app.updates.runner import TreeUpdateRunner


class UpdateCompositionError(RuntimeError):
    """The runtime configuration cannot compose the existing updater."""


def create_update_coordinator(
    runtime_config: str | Path,
    resource_manager: ResourceManager,
    *,
    install_root: str | Path | None = None,
    root_pid: int | None = None,
    report: Callable[[str, str], None] | None = None,
    before_install: Callable[[str], None] | None = None,
    after_install: Callable[[str], None] | None = None,
    on_restart_required: Callable[[], None] | None = None,
    automatic_check: bool = True,
) -> UpdateCoordinator | None:
    """Build the established resource and application update coordinator.

    ``install_root`` and ``root_pid`` identify the native desktop process, not
    this Python service. Omitting them preserves the original packaged Python
    client behavior for the still-supported V1 launcher.
    """

    try:
        service = load_update_service(runtime_config, resource_manager)
    except UpdateCompositionError as error:
        if report is not None:
            report("Update configuration", str(error))
        return None
    if service is None:
        return None

    application_check, application_install, application_installer = _application_updates(
        service,
        install_root=_resolved_install_root(install_root),
        root_pid=root_pid,
    )
    coordinator = UpdateCoordinator(
        service,
        resource_manager=resource_manager,
        before_install=before_install,
        after_install=after_install,
        record_install=lambda result: persist_installed_resource(
            Path(runtime_config).expanduser().resolve(),
            result.resource.resource_id,
            result.resource.version,
            result.validation.integrity_identity,
        ),
        application_check=application_check,
        application_install=application_install,
        application_installer=application_installer,
        on_restart_required=on_restart_required,
    )
    if automatic_check:
        coordinator.check_for_updates()
    return coordinator


def load_update_service(
    runtime_config: str | Path,
    resource_manager: ResourceManager,
) -> UpdateService | None:
    """Build the optional release-channel adapter from runtime metadata."""

    payload = _runtime_payload(runtime_config)
    updates = payload.get("updates")
    if updates is None or (isinstance(updates, Mapping) and updates.get("enabled") is False):
        return None
    if not isinstance(updates, Mapping):
        raise UpdateCompositionError("updates must be a JSON object")
    return UpdateService(resource_manager, _github_fetcher(updates))


def acknowledge_update_handoff(
    *,
    install_root: str | Path,
    legacy_ready_path: str | Path | None = None,
    challenge_path: str | Path | None = None,
) -> None:
    """Answer a root-authorized handoff after the native shell is ready.

    The caller is expected to expose this only through a host-only service
    request issued by the Rust process after its service handshake. Paths are
    constrained to the transaction or receipt directory for this installation.
    """

    if (legacy_ready_path is None) == (challenge_path is None):
        raise ValueError("exactly one update handoff path must be supplied")
    root = Path(install_root).expanduser().resolve()
    selected = Path(legacy_ready_path or challenge_path or "")
    if not selected.is_absolute() or len(str(selected)) > 4096:
        raise ValueError("update handoff path must be an absolute path under 4096 characters")

    if challenge_path is not None:
        expected_directory = receipt_store(root).directory.resolve()
        if selected.parent.resolve() != expected_directory or not selected.name.startswith(
            "challenge-"
        ) or not selected.name.endswith(".json"):
            raise ValueError("update challenge is outside this installation's receipt directory")
        confirm_started_v2(selected, install_root=root)
        return

    if (
        selected.parent.parent.resolve() != root.parent
        or not selected.parent.name.startswith(".hanly-update-")
        or selected.name != "ready"
    ):
        raise ValueError("legacy update marker is outside this installation's transaction")
    confirm_started(selected)


def _application_updates(
    service: UpdateService,
    *,
    install_root: Path | None,
    root_pid: int | None,
) -> tuple[
    Callable[[], ApplicationUpdate] | None,
    ApplicationInstall | None,
    TreeUpdateRunner | None,
]:
    """Configure build discovery and staging using the existing release fetcher."""

    fetcher = getattr(service, "fetcher", None)
    release_source = getattr(fetcher, "fetch_release", None)
    if fetcher is None or not callable(release_source):
        return None, None, None

    def check() -> ApplicationUpdate:
        return check_application_update(release_source, install_root=install_root)

    if install_root is None:
        return check, None, None

    runner = _tree_runner(fetcher, release_source, install_root, root_pid=root_pid)
    if runner is not None:
        return check, None, runner

    try:
        installer = ApplicationInstaller(fetcher, release_source, install_root=install_root)
    except ApplicationUpdateError:
        return check, None, None

    def install(update: ApplicationUpdate, on_progress: ProgressCallback | None) -> None:
        installer.apply(installer.stage(update, on_progress=on_progress))

    return check, install, None


def _tree_runner(
    fetcher: object,
    release_source: Callable[[], Any],
    install_root: Path,
    *,
    root_pid: int | None,
) -> TreeUpdateRunner | None:
    """Build the schema-2 updater for a stamped native desktop installation."""

    stamp = read_build_stamp()
    if stamp is None:
        return None
    store = receipt_store(install_root)
    tagged = getattr(fetcher, "fetch_release_by_tag", None)
    try:
        installer = TreeUpdateInstaller(
            cast(Any, fetcher),
            release_source,
            stamp=stamp,
            install_root=install_root,
            store=store,
            strategy=_staging_strategy(stamp, install_root, store, root_pid=root_pid),
            tagged_release_source=tagged if callable(tagged) else None,
        )
        return TreeUpdateRunner(
            installer, store=store, recovery_root=_default_recovery_directory()
        )
    except (DifferentialUpdateError, OSError):
        return None


def _staging_strategy(
    stamp: BuildStamp,
    install_root: Path,
    store: ReceiptStore,
    *,
    root_pid: int | None,
) -> WindowsFileStaging | PosixTreeStaging:
    """Choose the existing per-platform transaction strategy."""

    if stamp.platform == PLATFORM_WINDOWS:
        return WindowsFileStaging(
            install_root=install_root,
            executable=f"{APPLICATION_STEM}.exe",
            recovery_root=_default_recovery_directory(),
            store=store,
            source_commit=stamp.source_commit,
        )
    return PosixTreeStaging(
        install_root=install_root,
        platform=stamp.platform,
        store=store,
        source_commit=stamp.source_commit,
        owner_pid=root_pid,
    )


def _resolved_install_root(value: str | Path | None) -> Path | None:
    if value is None:
        return installation_root()
    root = Path(value).expanduser().resolve()
    return root if root.is_dir() else None


def _runtime_payload(runtime_config: str | Path) -> Mapping[str, Any]:
    path = Path(runtime_config).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateCompositionError(f"could not read update configuration: {error}") from error
    if not isinstance(payload, Mapping):
        raise UpdateCompositionError("runtime configuration must be a JSON object")
    return payload


def _github_fetcher(updates: Mapping[str, Any]) -> GitHubReleaseFetcher:
    github = updates.get("github", updates)
    if not isinstance(github, Mapping):
        raise UpdateCompositionError("updates.github must be a JSON object")
    owner = github.get("owner")
    repository = github.get("repository")
    if not isinstance(owner, str) or not isinstance(repository, str):
        raise UpdateCompositionError("updates.github requires owner and repository")
    tag = github.get("tag", "latest")
    manifest_asset = github.get("manifest_asset", "hanly-resources.json")
    if not isinstance(tag, str) or not isinstance(manifest_asset, str):
        raise UpdateCompositionError("update tag and manifest_asset must be strings")
    return GitHubReleaseFetcher(
        owner,
        repository,
        tag=tag,
        manifest_asset=manifest_asset,
    )


def _default_recovery_directory() -> Path:
    from hanly_app.paths import default_recovery_directory

    return default_recovery_directory()


__all__ = [
    "UpdateCompositionError",
    "acknowledge_update_handoff",
    "create_update_coordinator",
    "load_update_service",
]
