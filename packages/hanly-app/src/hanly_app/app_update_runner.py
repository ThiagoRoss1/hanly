"""Running one in-place update from the desktop, start to handoff.

:mod:`hanly_app.app_update_install` decides and stages; :mod:`hanly_app.app_update_helper`
applies. This is the seam between them and the rest of the desktop: it holds the
per-installation lock for the whole operation, refuses to let the application
quit until the helper has taken the transaction over, and settles whatever an
interrupted run left behind the next time Hanly starts.

Schema 2 keeps that shape for every platform. One runner holds the lock,
refuses to quit before a helper owns the transaction, and settles what an
interrupted run left behind; only the final apply differs, and it differs by
what was staged rather than by a test for the current platform.

The split into :meth:`prepare` and :meth:`install` is the user-facing contract,
not an implementation detail. Preparing reaches the network for two small
documents and reads the installation; it downloads no payload. Installing is
what the user authorized after being told the real size.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_build_identity import ReceiptStore
from .app_update_handoff import (
    NATIVE_HELPER_NAME,
    HandoffError,
    NativeTransaction,
    await_native_claim,
    clear_native_pending,
    native_pending,
    read_descriptor,
    read_native_result,
    record_native_pending,
    start_native_helper,
)
from .app_update_helper import (
    HelperError,
    await_claim,
    clear_recovery_copy,
    helper_is_running,
    pending_transaction,
    recover_pending,
    start_helper,
)
from .app_update_install import (
    DifferentialInstaller,
    DifferentialUpdateError,
    PreparedTreeUpdate,
    PreparedUpdate,
    StagedPosixTransaction,
    StagedTreeUpdate,
    StagedUpdate,
    TreeUpdateInstaller,
    UpdateCancelled,
)
from .app_update_journal import (
    COMMITTED,
    RECOVERY_REQUIRED,
    RESTORED,
    InstallLock,
    JournalError,
    UpdateJournal,
    journals_in,
    unsettled_journals,
    working_root,
)
from .app_update_plan import FROM_DELTA
from .update_service import ProgressCallback

CancelHook = Callable[[], bool]
Reporter = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class SettledUpdate:
    """What a previous run of the updater turned out to have done."""

    outcome: str
    detail: str
    version: str | None = None

    @property
    def needs_attention(self) -> bool:
        return self.outcome == RECOVERY_REQUIRED


class InPlaceUpdateRunner:
    """One installation's differential updater, for the length of a session."""

    def __init__(self, installer: DifferentialInstaller, *, recovery_root: Path) -> None:
        self._installer = installer
        self._recovery_root = Path(recovery_root)
        self._lock = InstallLock(installer.install_root)
        self._staged: StagedUpdate | None = None

    @property
    def install_root(self) -> Path:
        return self._installer.install_root

    def prepare(
        self,
        version: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> PreparedUpdate:
        """Decide the update, holding the installation for the whole operation."""

        self._acquire()
        try:
            return self._installer.prepare(
                version, on_progress=on_progress, should_cancel=should_cancel
            )
        except BaseException:
            self._release()
            raise

    def install(
        self,
        prepared: PreparedUpdate,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> None:
        """Stage the payload and hand the transaction to the native helper.

        On return the helper owns the installation and is waiting for this
        process to exit. Nothing has been changed yet, and nothing will be
        until Hanly stops.
        """

        try:
            staged = self._installer.stage(
                prepared, on_progress=on_progress, should_cancel=should_cancel
            )
            self._staged = staged
            start_helper(staged.journal, self._recovery_root)
            await_claim(staged.journal)
        except (DifferentialUpdateError, HelperError, JournalError):
            self.abandon()
            raise

    def abandon(self) -> None:
        """Drop a transaction nothing has acted on, and release the lock.

        Only ever called before the helper has started changing files: what it
        removes is downloaded payload and an unused journal, never a backup.
        """

        staged = self._staged
        self._staged = None
        if staged is not None and staged.journal.is_settled():
            _remove(staged.journal.directory)
        clear_recovery_copy(self._recovery_root)
        self._release()

    def _acquire(self) -> None:
        try:
            self._lock.acquire()
        except JournalError as error:
            raise DifferentialUpdateError(str(error)) from error

    def _release(self) -> None:
        self._lock.release()


def settle_previous_update(
    install_root: Path,
    recovery_root: Path,
    *,
    report: Reporter | None = None,
) -> SettledUpdate | None:
    """Report and clean up after the update that ran before this launch.

    A committed or restored transaction is removed and reported. An unsettled
    one is handed back to the native helper: the installation may be
    mid-replacement, and this interpreter is running out of it.
    """

    root = working_root(install_root)
    if not root.is_dir():
        clear_recovery_copy(recovery_root)
        return None

    unsettled = unsettled_journals(install_root)
    if unsettled:
        return _hand_back(unsettled[-1], recovery_root, report)

    settled: SettledUpdate | None = None
    for journal in tuple(journals_in(install_root)):
        result = journal.read_result()
        if result is not None:
            settled = SettledUpdate(
                outcome=str(result.get("outcome") or COMMITTED),
                detail=str(result.get("detail") or ""),
                version=_version_of(journal),
            )
        _remove(journal.directory)

    clear_recovery_copy(recovery_root)
    _remove_if_empty(root)
    if settled is not None and report is not None:
        report("Update", settled.detail or f"The previous update {settled.outcome}.")
    return settled


def _hand_back(
    journal: UpdateJournal, recovery_root: Path, report: Reporter | None
) -> SettledUpdate:
    """Restart the helper for a transaction that never reached an outcome.

    The commonest one is the update being applied right now, since the helper
    launches this very build and waits for it to answer. A live helper is left
    alone: two programs moving the same files is what must not happen.
    """

    claim = journal.helper_claim() or {}
    owner = claim.get("pid")
    if isinstance(owner, int) and helper_is_running(owner):
        return SettledUpdate(
            outcome=RECOVERY_REQUIRED,
            detail="An update is being applied.",
            version=_version_of(journal),
        )

    pending = pending_transaction(recovery_root)
    if pending is None or Path(pending) != journal.directory:
        return SettledUpdate(
            outcome=RECOVERY_REQUIRED,
            detail=(
                "An interrupted update is still outstanding, and its recovery "
                "record is missing. Nothing was removed."
            ),
            version=_version_of(journal),
        )
    try:
        recover_pending(recovery_root)
    except HelperError as error:
        if report is not None:
            report("Update", f"Could not finish the interrupted update: {error}")
        return SettledUpdate(outcome=RECOVERY_REQUIRED, detail=str(error))
    if report is not None:
        report("Update", "Finishing an update that was interrupted.")
    return SettledUpdate(
        outcome=RECOVERY_REQUIRED,
        detail="An interrupted update is being finished.",
        version=_version_of(journal),
    )


def describe_outcome(settled: SettledUpdate) -> str:
    """One sentence a person can act on, for the session log and the page."""

    if settled.outcome == COMMITTED:
        return f"Hanly updated to {settled.version}." if settled.version else "Hanly updated."
    if settled.outcome == RESTORED:
        return settled.detail or "The update was undone and the previous version is back."
    return settled.detail or "An update did not finish and needs attention."


def source_label(prepared: PreparedUpdate) -> str:
    """Whether this update is the small one or the whole application."""

    return "differential" if prepared.plan.source == FROM_DELTA else "full"


def _version_of(journal: UpdateJournal) -> str | None:
    try:
        return journal.read_plan().target.version
    except JournalError:
        return None


def _remove(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except (OSError, NotADirectoryError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_if_empty(path: Path) -> None:
    try:
        next(path.iterdir())
    except StopIteration:
        try:
            path.rmdir()
        except OSError:
            pass
    except OSError:
        pass


# --------------------------------------------------------------------------
# Schema 2: one runner, three ways of applying what it decided
# --------------------------------------------------------------------------


class TreeUpdateRunner:
    """One installation's updater, whichever platform it is running on.

    The lock lifecycle, the refusal to quit before a helper owns the
    transaction, and the settling of whatever a previous run left behind are
    the same everywhere. Only the last step differs, and it differs by what was
    staged rather than by a test for the current platform.
    """

    def __init__(
        self,
        installer: TreeUpdateInstaller,
        *,
        store: ReceiptStore,
        recovery_root: Path,
    ) -> None:
        self._installer = installer
        self._store = store
        self._recovery_root = Path(recovery_root)
        self._lock = InstallLock(installer.install_root, directory=store.directory)
        self._staged: StagedTreeUpdate | None = None

    @property
    def install_root(self) -> Path:
        return self._installer.install_root

    def prepare(
        self,
        version: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> PreparedTreeUpdate:
        """Decide the update, holding the installation for the whole operation."""

        self._acquire()
        try:
            return self._installer.prepare(
                version, on_progress=on_progress, should_cancel=should_cancel
            )
        except BaseException:
            self._release()
            raise

    def install(
        self,
        prepared: PreparedTreeUpdate,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> None:
        """Stage the payload and hand the transaction to the native helper.

        On return the helper owns the installation and is waiting for this
        process to exit. Nothing has been changed yet, and nothing will be
        until Hanly stops.
        """

        try:
            staged = self._installer.stage(
                prepared, on_progress=on_progress, should_cancel=should_cancel
            )
            self._staged = staged
            self._hand_off(staged)
        except (DifferentialUpdateError, HandoffError, HelperError, JournalError):
            self.abandon()
            raise

    def abandon(self) -> None:
        """Drop a transaction nothing has acted on, and release the lock.

        Only ever called before a helper has started changing anything: what it
        removes is a downloaded payload, an unused journal, and a candidate
        nobody installed - never a backup.
        """

        staged = self._staged
        self._staged = None
        if staged is not None:
            _discard_transaction(staged.transaction)
        clear_recovery_copy(self._recovery_root)
        clear_native_pending(self._store.directory)
        self._store.restore_previous()
        self._release()

    def _hand_off(self, staged: StagedTreeUpdate) -> None:
        """Give the transaction away, and wait until it is genuinely owned."""

        transaction = staged.transaction
        if isinstance(transaction, StagedPosixTransaction):
            record_native_pending(self._store.directory, transaction.descriptor_path)
            start_native_helper(transaction.helper_path, transaction.descriptor_path)
            await_native_claim(transaction.lock_path)
            return
        start_helper(transaction.journal, self._recovery_root)
        await_claim(transaction.journal)

    def _acquire(self) -> None:
        try:
            self._lock.acquire()
        except JournalError as error:
            raise DifferentialUpdateError(str(error)) from error

    def _release(self) -> None:
        self._lock.release()


def settle_native_update(
    store: ReceiptStore, *, report: Reporter | None = None
) -> SettledUpdate | None:
    """Report and clean up after whatever POSIX update ran before this launch.

    A settled transaction is read, reported, and removed. An unsettled one is
    handed back to the native helper, which decides from the filesystem rather
    than from a record: this launch may itself be the candidate the helper is
    waiting for, and it may equally be an old build that came back.
    """

    descriptor_path = native_pending(store.directory)
    if descriptor_path is None:
        return None
    try:
        transaction = read_descriptor(descriptor_path)
    except HandoffError as error:
        clear_native_pending(store.directory)
        return SettledUpdate(outcome=RECOVERY_REQUIRED, detail=str(error))

    settled = read_native_result(transaction.result_path)
    if settled is None:
        return _recover_native(store, transaction, descriptor_path, report)

    outcome, detail = settled
    _remove(transaction.staging_path)
    clear_native_pending(store.directory)
    if report is not None:
        report("Update", detail or f"The previous update {outcome}.")
    # The descriptor names a transaction, not a version: the helper is told what
    # to accept as an answer, never what to call the build it installed.
    return SettledUpdate(outcome=outcome, detail=detail)


def _recover_native(
    store: ReceiptStore,
    transaction: NativeTransaction,
    descriptor_path: Path,
    report: Reporter | None,
) -> SettledUpdate:
    """Restart the helper for a transaction that never reached an outcome."""

    helper = store.directory / NATIVE_HELPER_NAME
    if not helper.is_file():
        return SettledUpdate(
            outcome=RECOVERY_REQUIRED,
            detail=(
                "An interrupted update is still outstanding, and the program that finishes "
                "it is missing. Nothing was removed."
            ),
        )
    try:
        start_native_helper(helper, descriptor_path, recover=True)
    except HandoffError as error:
        if report is not None:
            report("Update", f"Could not finish the interrupted update: {error}")
        return SettledUpdate(outcome=RECOVERY_REQUIRED, detail=str(error))
    if report is not None:
        report("Update", "Finishing an update that was interrupted.")
    return SettledUpdate(
        outcome=RECOVERY_REQUIRED, detail="An interrupted update is being finished."
    )


def _discard_transaction(transaction: Any) -> None:
    """Remove whatever a staging strategy left, whichever one it was."""

    if isinstance(transaction, StagedPosixTransaction):
        _remove(transaction.directory)
        return
    journal = getattr(transaction, "journal", None)
    if journal is not None and journal.is_settled():
        _remove(journal.directory)


__all__ = [
    "CancelHook",
    "InPlaceUpdateRunner",
    "Reporter",
    "SettledUpdate",
    "TreeUpdateRunner",
    "UpdateCancelled",
    "describe_outcome",
    "settle_native_update",
    "settle_previous_update",
    "source_label",
]
