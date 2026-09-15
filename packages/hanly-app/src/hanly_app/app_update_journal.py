"""The durable record of one in-place update, and the paths it owns.

Replacing a directory is one rename, and a rename either happened or did not.
Replacing forty files inside a directory is forty renames, and an interruption
can land between any two of them - or between a rename and the record of it.
This module is what makes that recoverable: a plan written once before anything
moves, and a running record of intent flushed before each mutation.

Correctness does not depend on the running record. Every apply and rollback
step is decided from what is actually on disk, so a step interrupted after the
filesystem succeeded and before the journal was updated replays to the same
result. The record exists so a helper can resume in bounded time, so progress
can be shown, and so a person can be told what happened.

Layout, all inside ``<installation>/.hanly-update/<transaction>/``::

    plan.json        written once; the root, the identities, the operations
    progress.jsonl   appended as the apply runs
    helper.json      the helper's acknowledgement that it owns the transaction
    ready.txt        the new build's report that it started
    result.json      the settled outcome
    payload/NNNN     one staged file per add or replace
    backup/NNNN      the original of one replaced or deleted file

Staged and backed-up files are named by operation index rather than by mirroring
the installed tree. A payload path is then always short and always plain ASCII,
whatever the installation is called, and the journal is the only thing that maps
one back to where it belongs.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_manifest import (
    WORKING_DIRECTORY_NAME,
    BuildIdentity,
    ManifestError,
    require_safe_relative_path,
)
from .app_update_plan import ADD, DELETE, REPLACE, TreePlan, UpdatePlan
from .owned_cleanup import _process_alive

JOURNAL_VERSION = 1

PLAN_NAME = "plan.json"
PROGRESS_NAME = "progress.jsonl"
HELPER_NAME = "helper.json"
READY_NAME = "ready.txt"
EXPECTED_NAME = "expected.txt"
RESULT_NAME = "result.json"
PAYLOAD_DIRECTORY = "payload"
BACKUP_DIRECTORY = "backup"

#: What the transaction is doing. ``applying`` and ``rolling-back`` are the two
#: states in which the installation is not known to be whole.
PREPARED = "prepared"
APPLYING = "applying"
AWAITING_STARTUP = "awaiting-startup"
COMMITTED = "committed"
ROLLING_BACK = "rolling-back"
RESTORED = "restored"
RECOVERY_REQUIRED = "recovery-required"

#: Phases in which an interrupted transaction must be finished or undone before
#: the installation can be trusted to launch.
UNSETTLED_PHASES = frozenset({APPLYING, AWAITING_STARTUP, ROLLING_BACK, RECOVERY_REQUIRED})

#: Which apply strategy a transaction was written for. A helper that read the
#: wrong one would act on operations that do not describe its own work.
RECORD_WINDOWS_FILES = "windows-files"
RECORD_POSIX_TREE = "posix-tree"


class JournalError(RuntimeError):
    """Raised when a transaction record cannot be written or trusted."""


@dataclass(frozen=True, slots=True)
class JournalOperation:
    """One file change, and everywhere its data lives while it happens."""

    index: int
    kind: str
    path: str
    component: str = "application"
    target_sha256: str | None = None
    target_size: int = 0
    current_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in (ADD, REPLACE, DELETE):
            raise JournalError(f"{self.kind!r} is not an operation this journal records")
        require_safe_relative_path(self.path)
        if self.kind in (ADD, REPLACE) and not self.target_sha256:
            raise JournalError(f"{self.path} is written without a target digest")

    @property
    def payload_name(self) -> str:
        return f"{PAYLOAD_DIRECTORY}/{self.index:04d}"

    @property
    def backup_name(self) -> str:
        return f"{BACKUP_DIRECTORY}/{self.index:04d}"

    @property
    def writes_a_file(self) -> bool:
        return self.kind in (ADD, REPLACE)

    @property
    def keeps_a_backup(self) -> bool:
        return self.kind in (REPLACE, DELETE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "path": self.path,
            "component": self.component,
            "target_sha256": self.target_sha256,
            "target_size": self.target_size,
            "current_sha256": self.current_sha256,
            "payload": self.payload_name if self.writes_a_file else None,
            "backup": self.backup_name if self.keeps_a_backup else None,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> JournalOperation:
        if not isinstance(payload, Mapping):
            raise JournalError("a journal operation must be a JSON object")
        index = payload.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise JournalError("a journal operation needs a positive index")
        size = payload.get("target_size") or 0
        return cls(
            index=index,
            kind=str(payload.get("kind")),
            path=str(payload.get("path")),
            component=str(payload.get("component") or "application"),
            target_sha256=_optional_text(payload.get("target_sha256")),
            target_size=size if isinstance(size, int) and not isinstance(size, bool) else 0,
            current_sha256=_optional_text(payload.get("current_sha256")),
        )


@dataclass(frozen=True, slots=True)
class TransactionPlan:
    """Everything the helper needs, decided before the helper exists."""

    transaction_id: str
    install_root: Path
    executable: str
    target: BuildIdentity
    base: BuildIdentity | None
    operations: tuple[JournalOperation, ...]
    recovery_root: Path
    created: float
    #: Which apply strategy wrote this. Absent means the schema-1 Windows one,
    #: which is what a transaction left by an older Hanly is.
    record: str = RECORD_WINDOWS_FILES
    #: The schema-2 identity of the build being installed. Empty for a
    #: transaction an older Hanly staged, which knew only a version.
    manifest_sha256: str = ""
    #: Where the new build proves it started, and where the receipt describing
    #: the previous one waits in case it has to go back.
    challenge_path: Path | None = None
    receipt_path: Path | None = None

    @property
    def total_bytes(self) -> int:
        return sum(item.target_size for item in self.operations)

    @property
    def is_schema_two(self) -> bool:
        return bool(self.manifest_sha256)

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_version": JOURNAL_VERSION,
            "transaction_id": self.transaction_id,
            "install_root": str(self.install_root),
            "executable": self.executable,
            "target": self.target.to_dict(),
            "base": None if self.base is None else self.base.to_dict(),
            "recovery_root": str(self.recovery_root),
            "created": self.created,
            "record": self.record,
            "manifest_sha256": self.manifest_sha256,
            "challenge": None if self.challenge_path is None else str(self.challenge_path),
            "receipt": None if self.receipt_path is None else str(self.receipt_path),
            "operations": [item.to_dict() for item in self.operations],
        }

    @classmethod
    def from_payload(cls, payload: Any) -> TransactionPlan:
        if not isinstance(payload, Mapping):
            raise JournalError("a transaction plan must be a JSON object")
        if payload.get("journal_version") != JOURNAL_VERSION:
            raise JournalError("the transaction plan was written by a different Hanly")
        operations = payload.get("operations")
        if not isinstance(operations, (list, tuple)):
            raise JournalError("a transaction plan must list its operations")
        base = payload.get("base")
        created = payload.get("created")
        return cls(
            transaction_id=str(payload.get("transaction_id") or ""),
            install_root=Path(str(payload.get("install_root"))),
            executable=str(payload.get("executable")),
            target=BuildIdentity.from_payload(payload.get("target")),
            base=None if base is None else BuildIdentity.from_payload(base),
            operations=tuple(JournalOperation.from_payload(item) for item in operations),
            recovery_root=Path(str(payload.get("recovery_root"))),
            created=float(created) if isinstance(created, (int, float)) else 0.0,
            record=str(payload.get("record") or RECORD_WINDOWS_FILES),
            manifest_sha256=str(payload.get("manifest_sha256") or ""),
            challenge_path=_optional_path(payload.get("challenge")),
            receipt_path=_optional_path(payload.get("receipt")),
        )


class UpdateJournal:
    """One transaction directory, and every read and write it permits.

    Nothing outside the transaction directory is touched here. Moving files in
    and out of the installation is the helper's work, and it is done natively so
    that it does not depend on the interpreter it is replacing.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def plan_path(self) -> Path:
        return self._directory / PLAN_NAME

    @property
    def progress_path(self) -> Path:
        return self._directory / PROGRESS_NAME

    @property
    def helper_path(self) -> Path:
        return self._directory / HELPER_NAME

    @property
    def ready_path(self) -> Path:
        return self._directory / READY_NAME

    @property
    def expected_path(self) -> Path:
        """The exact bytes a helper accepts as this transaction's answer.

        Written here so a helper compares two files rather than reassembling a
        record: the native POSIX helper has no JSON parser, and reading the
        expected answer out of a file is the one thing both helpers can do.
        """

        return self._directory / EXPECTED_NAME

    @property
    def result_path(self) -> Path:
        return self._directory / RESULT_NAME

    @property
    def payload_root(self) -> Path:
        return self._directory / PAYLOAD_DIRECTORY

    @property
    def backup_root(self) -> Path:
        return self._directory / BACKUP_DIRECTORY

    def payload_for(self, operation: JournalOperation) -> Path:
        return self._directory / operation.payload_name

    def prepare(self, plan: TransactionPlan) -> None:
        """Create the directories and write the plan, once, before anything."""

        for directory in (self._directory, self.payload_root, self.backup_root):
            directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.plan_path, json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        self.record(PREPARED)

    def read_plan(self) -> TransactionPlan:
        try:
            payload = json.loads(self.plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise JournalError(f"could not read {self.plan_path}: {error}") from error
        try:
            return TransactionPlan.from_payload(payload)
        except (ManifestError, JournalError) as error:
            raise JournalError(f"{self.plan_path} is not a usable plan: {error}") from error

    def record(self, phase: str, *, operation: int | None = None, detail: str = "") -> None:
        """Append one record and flush it, before the mutation it describes."""

        entry: dict[str, Any] = {"at": time.time(), "phase": phase}
        if operation is not None:
            entry["operation"] = operation
        if detail:
            entry["detail"] = detail
        try:
            with self.progress_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise JournalError(f"could not record update progress: {error}") from error

    def records(self) -> tuple[dict[str, Any], ...]:
        """Every record written so far, ignoring a torn final line."""

        try:
            text = self.progress_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return ()
        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(value)
        return tuple(entries)

    def phase(self) -> str:
        """The last phase recorded, or ``prepared`` for a fresh transaction."""

        for entry in reversed(self.records()):
            phase = entry.get("phase")
            if isinstance(phase, str):
                return phase
        return PREPARED

    def is_settled(self) -> bool:
        return self.phase() not in UNSETTLED_PHASES

    def write_result(self, outcome: str, detail: str = "") -> None:
        _write_atomic(
            self.result_path,
            json.dumps(
                {"outcome": outcome, "detail": detail, "at": time.time()},
                indent=2,
                sort_keys=True,
            ),
        )

    def read_result(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.result_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def helper_claim(self) -> dict[str, Any] | None:
        """What the helper wrote when it took ownership, if it has."""

        try:
            value = json.loads(self.helper_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None


def working_root(install_root: Path) -> Path:
    """The one directory inside an installation the updater may create."""

    return Path(install_root) / WORKING_DIRECTORY_NAME


#: Claimed for the whole length of an update, by whichever process is running
#: it. The coordinator's own lock is per process, and two Hanlys started from
#: one installation are two processes.
LOCK_NAME = "lock.json"


class InstallLock:
    """One update at a time per installation, across every process.

    A lock whose owner is gone is taken over rather than honoured: a process
    killed mid-update leaves the file behind, and refusing every later update
    because of it would make a crash permanent.
    """

    def __init__(self, install_root: Path, *, directory: Path | None = None) -> None:
        # POSIX never writes inside an installation, so its lock lives in the
        # per-user update directory instead of in the tree being replaced.
        root = working_root(install_root) if directory is None else Path(directory)
        self._path = root / LOCK_NAME
        self._held = False

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> None:
        """Take the lock, or say who has it.

        Creation is exclusive rather than a read followed by a write, so two
        processes arriving together cannot both decide the lock was free.
        """

        self._path.parent.mkdir(parents=True, exist_ok=True)
        claim = json.dumps({"pid": os.getpid(), "at": time.time()}, sort_keys=True)
        try:
            with open(self._path, "x", encoding="utf-8") as stream:
                stream.write(claim)
        except FileExistsError:
            holder = self.holder()
            if holder is not None and holder != os.getpid():
                raise JournalError(
                    "another Hanly process is already updating this installation"
                ) from None
            # Nothing alive owns it: a process was killed mid-update, and
            # honouring the file it left would make that crash permanent.
            _write_atomic(self._path, claim)
        except OSError as error:
            raise JournalError(f"could not claim {self._path}: {error}") from error
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def holder(self) -> int | None:
        """The live process holding this lock, or None if nothing does."""

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            return None
        return pid if _process_alive(pid) else None

    def __enter__(self) -> InstallLock:
        self.acquire()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.release()


def journals_in(install_root: Path) -> Iterator[UpdateJournal]:
    """Every transaction an installation currently carries, newest last."""

    root = working_root(install_root)
    if not root.is_dir():
        return
    for candidate in sorted(root.iterdir()):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if (candidate / PLAN_NAME).is_file():
            yield UpdateJournal(candidate)


def unsettled_journals(install_root: Path) -> tuple[UpdateJournal, ...]:
    """Transactions that left the installation in an unknown state."""

    return tuple(journal for journal in journals_in(install_root) if not journal.is_settled())


def operations_for(plan: UpdatePlan) -> tuple[JournalOperation, ...]:
    """Number a decided plan's operations into the order they are applied.

    Additions and replacements come before deletions: a file the new build
    needs is in place before anything the old build had is taken away, so an
    interruption in the middle leaves more of a working installation rather
    than less.
    """

    return tuple(
        JournalOperation(
            index=index,
            kind=item.kind,
            path=item.path,
            component=item.component,
            target_sha256=None if item.target is None else item.target.sha256,
            target_size=item.size,
            current_sha256=item.current_sha256,
        )
        for index, item in enumerate(plan.operations, start=1)
    )


def _write_atomic(path: Path, text: str) -> None:
    """Write a whole file or none of it, so no reader sees half a document."""

    temporary = path.with_name(f"{path.name}.partial")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise JournalError(f"could not write {path}: {error}") from error


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_path(value: Any) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


# --------------------------------------------------------------------------
# Schema 2: transaction identity, and the acknowledgement that commits one
#
# A version number is not an acknowledgement. The old contract had the new
# build write its version into a file, which any build of that version - and
# any leftover file - satisfies. Schema 2 binds the answer to one transaction,
# one random nonce, one build UUID, and one manifest digest, so the only thing
# that can produce it is the build this transaction installed, started from the
# path this transaction installed it to.
# --------------------------------------------------------------------------

#: What an acknowledgement file is called, derived from its own challenge so a
#: helper can name both from one argument.
ACK_SUFFIX = ".ack"

#: The first line of a V2 acknowledgement, and what tells a helper it is not
#: reading a legacy version-text file.
ACK_MAGIC = "HANLY-READY-2"

#: The fields after the magic, in the order both sides read them.
ACK_FIELDS = (
    "transaction",
    "nonce",
    "product",
    "platform",
    "architecture",
    "version",
    "build_id",
    "manifest_sha256",
)

#: Bits of randomness in a challenge. A helper that accepted a guessable answer
#: would commit to whatever wrote the file first.
NONCE_BITS = 256

#: A transaction is named by the directory holding it, which the system's own
#: temporary-name alphabet may spell with an underscore.
_TRANSACTION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_NONCE = re.compile(r"^[0-9a-f]{32,128}$")

#: Both documents are one small record; a larger file is not one of ours.
MAX_CHALLENGE_BYTES = 64 * 1024

#: Written beside the receipt before a candidate is launched, so a rollback can
#: put back what the installation was known to be.
RECEIPT_BACKUP_SUFFIX = ".previous"


class AcknowledgementError(JournalError):
    """Raised when a startup acknowledgement is absent, stale, or not ours."""


@dataclass(frozen=True, slots=True)
class UpdateChallenge:
    """What the new build must prove before an update is committed.

    Kept private to this installation's own update directory. It is a question,
    not an answer: it names the expected identity so a candidate can check it
    is the right build, and the candidate answers from its *own* stamp, so
    echoing the expectation back is not an acknowledgement.
    """

    transaction_id: str
    nonce: str
    identity: BuildIdentity
    manifest_sha256: str
    install_root: str

    def __post_init__(self) -> None:
        if not _TRANSACTION_ID.match(self.transaction_id):
            raise AcknowledgementError("an update challenge needs a plain transaction name")
        if not _NONCE.match(self.nonce):
            raise AcknowledgementError("an update challenge needs a random hexadecimal nonce")
        if len(self.manifest_sha256) != 64:
            raise AcknowledgementError("an update challenge names its manifest by SHA-256")

    def expected(self) -> str:
        """The exact bytes a helper compares an acknowledgement against."""

        return _acknowledgement_text(
            transaction=self.transaction_id,
            nonce=self.nonce,
            identity=self.identity,
            manifest_sha256=self.manifest_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction": self.transaction_id,
            "nonce": self.nonce,
            "identity": self.identity.to_dict(),
            "manifest_sha256": self.manifest_sha256,
            "install_root": self.install_root,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> UpdateChallenge:
        if not isinstance(payload, Mapping):
            raise AcknowledgementError("an update challenge must be a JSON object")
        try:
            return cls(
                transaction_id=str(payload.get("transaction") or ""),
                nonce=str(payload.get("nonce") or ""),
                identity=BuildIdentity.from_payload(payload.get("identity")),
                manifest_sha256=str(payload.get("manifest_sha256") or "").lower(),
                install_root=str(payload.get("install_root") or ""),
            )
        except ManifestError as error:
            raise AcknowledgementError(f"the update challenge is not usable: {error}") from error


def new_challenge(
    transaction_id: str,
    identity: BuildIdentity,
    manifest_sha256: str,
    install_root: Path,
) -> UpdateChallenge:
    """Pose the question this one transaction will accept an answer to."""

    return UpdateChallenge(
        transaction_id=transaction_id,
        nonce=secrets.token_hex(NONCE_BITS // 8),
        identity=identity,
        manifest_sha256=manifest_sha256,
        install_root=str(Path(install_root)),
    )


def write_challenge(path: Path, challenge: UpdateChallenge) -> Path:
    """Write the challenge where only this installation's updater can read it."""

    _write_atomic(path, json.dumps(challenge.to_dict(), indent=2, sort_keys=True))
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows has no mode to set here; the directory is already per-user.
        pass
    return path


def read_challenge(path: Path) -> UpdateChallenge:
    """Read a challenge a candidate has been pointed at, refusing a stray file."""

    try:
        if path.is_symlink():
            raise AcknowledgementError(f"{path} is a link, not an update challenge")
        if path.stat().st_size > MAX_CHALLENGE_BYTES:
            raise AcknowledgementError(f"{path} is larger than an update challenge")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcknowledgementError(f"could not read {path}: {error}") from error
    return UpdateChallenge.from_payload(payload)


def acknowledgement_path(challenge_path: Path) -> Path:
    """Where the answer to one challenge is written, beside the question."""

    return Path(challenge_path).with_suffix(ACK_SUFFIX)


def write_acknowledgement(
    path: Path, challenge: UpdateChallenge, identity: BuildIdentity
) -> Path:
    """Answer a challenge with the running build's own identity.

    ``identity`` comes from the candidate's embedded stamp, never from the
    challenge: a build that copied the expected answer out of the question
    would prove only that it could read the question.
    """

    text = _acknowledgement_text(
        transaction=challenge.transaction_id,
        nonce=challenge.nonce,
        identity=identity,
        manifest_sha256=challenge.manifest_sha256,
    )
    _write_atomic(path, text)
    return path


def acknowledgement_matches(text: str, challenge: UpdateChallenge) -> bool:
    """Whether one file's exact bytes commit this transaction.

    Compared as whole text rather than field by field so the native helper can
    do the same comparison without a JSON parser.
    """

    return text == challenge.expected()


def _acknowledgement_text(
    *, transaction: str, nonce: str, identity: BuildIdentity, manifest_sha256: str
) -> str:
    values = {
        "transaction": transaction,
        "nonce": nonce,
        "product": identity.product,
        "platform": identity.platform,
        "architecture": identity.architecture,
        "version": identity.version,
        "build_id": identity.build_id,
        "manifest_sha256": manifest_sha256,
    }
    for name, value in values.items():
        if not value or "\n" in value or "\r" in value:
            raise AcknowledgementError(f"{name} cannot appear in an acknowledgement")
    return "\n".join([ACK_MAGIC, *(values[name] for name in ACK_FIELDS)]) + "\n"


def tree_operations_for(plan: TreePlan) -> tuple[JournalOperation, ...]:
    """Number a schema-2 plan's file changes into the order they are applied.

    Only files whose bytes actually change appear, plus the deletions:
    directories are created by the move that needs them, and a build that
    reached a release carrying an empty directory or a link on Windows was
    refused by the producer long before this.
    """

    operations: list[JournalOperation] = []
    for item in plan.operations:
        entry = item.target if item.target is not None else item.current
        if entry is None or not entry.is_file:
            continue
        if item.kind != DELETE and not item.needs_bytes:
            continue
        operations.append(
            JournalOperation(
                index=len(operations) + 1,
                kind=item.kind,
                path=item.path,
                component=item.component,
                target_sha256=None if item.target is None else item.target.sha256,
                target_size=item.size,
                current_sha256=None if item.current is None else item.current.sha256,
            )
        )
    return tuple(operations)


__all__ = [
    "ACK_FIELDS",
    "ACK_MAGIC",
    "ACK_SUFFIX",
    "APPLYING",
    "AWAITING_STARTUP",
    "BACKUP_DIRECTORY",
    "COMMITTED",
    "EXPECTED_NAME",
    "HELPER_NAME",
    "JOURNAL_VERSION",
    "LOCK_NAME",
    "MAX_CHALLENGE_BYTES",
    "NONCE_BITS",
    "PAYLOAD_DIRECTORY",
    "PLAN_NAME",
    "PREPARED",
    "PROGRESS_NAME",
    "READY_NAME",
    "RECEIPT_BACKUP_SUFFIX",
    "RECORD_POSIX_TREE",
    "RECORD_WINDOWS_FILES",
    "RECOVERY_REQUIRED",
    "RESTORED",
    "RESULT_NAME",
    "ROLLING_BACK",
    "UNSETTLED_PHASES",
    "AcknowledgementError",
    "InstallLock",
    "JournalError",
    "JournalOperation",
    "TransactionPlan",
    "UpdateChallenge",
    "UpdateJournal",
    "acknowledgement_matches",
    "acknowledgement_path",
    "journals_in",
    "new_challenge",
    "operations_for",
    "read_challenge",
    "tree_operations_for",
    "unsettled_journals",
    "working_root",
    "write_acknowledgement",
    "write_challenge",
]
