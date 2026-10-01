"""Fixed scenario inventory and the evidence each scenario can establish."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """One bounded check with explicit prerequisites and evidence limits."""

    id: str
    area: str
    title: str
    targets: tuple[str, ...]
    evidence: str
    expected: str
    platforms: tuple[str, ...] = ()
    timeout_seconds: int = 300
    needs_bundle: bool = False
    observe_identity: bool = False


SCENARIOS = (
    Scenario(
        "APP-STARTUP",
        "startup",
        "Desktop readiness and shutdown",
        ("tests/native/shared/test_desktop_startup.py",),
        "real_source_app",
        "Ready without capture; shell and owned children exit.",
        timeout_seconds=480,
        observe_identity=True,
    ),
    Scenario(
        "CC-LIFECYCLE",
        "control_center",
        "Open, close and reopen the window",
        (
            "tests/native/shared/test_control_center_lifecycle.py::"
            "test_the_window_opens_closes_and_reopens_without_touching_the_shell",
        ),
        "real_ui_injected_bridge",
        "The shell survives both windows and owns no WebEngine.",
        observe_identity=True,
    ),
    Scenario(
        "CC-CONTROLS",
        "control_center",
        "Choice controls and responsive layout",
        (
            "tests/native/shared/test_control_center_combobox.py",
            "tests/native/shared/test_control_center_layout.py",
        ),
        "real_ui_injected_bridge",
        "Choices respond to input and controls stay inside the page.",
    ),
    Scenario(
        "CC-UPDATE-STAGE",
        "updater_ui",
        "Update stage transitions and progress",
        ("tests/native/shared/test_update_stage_animation.py",),
        "real_ui_injected_update",
        "Stage motion happens once per changed label, not per poll.",
    ),
    Scenario(
        "CAPTURE-CHOICE",
        "capture",
        "Capture selection closes during quit",
        ("tests/native/shared/test_capture_prompt_shutdown.py",),
        "real_ui_simulated_input",
        "Quit closes either choice and releases its nested loop.",
    ),
    Scenario(
        "HOVER-POPUP",
        "hover_popup",
        "Hover scheduling and popup lifecycle",
        (
            "tests/native/shared/test_qt_hover_scheduler.py",
            "tests/native/shared/test_qt_popup_window.py",
            "tests/native/shared/test_hover_exit_qt.py",
        ),
        "real_ui_simulated_lookup",
        "Latest requests present correctly and popup exit stays usable.",
    ),
    Scenario(
        "SETTINGS",
        "settings",
        "Configuration and Control Center actions",
        ("tests/test_app_config.py", "tests/test_control_center.py"),
        "simulated_services",
        "Persisted preferences and bridge actions satisfy their contracts.",
    ),
    Scenario(
        "UPDATE-COORDINATOR",
        "updater",
        "Update preparation, confirmation and failures",
        ("tests/test_update_coordinator.py",),
        "simulated_delivery",
        "States reflect confirmation, cancellation, staging and errors.",
    ),
    Scenario(
        "UPDATE-APPLY-POSIX",
        "updater",
        "Native apply, acknowledgement and rollback",
        ("tests/native/shared/test_update_posix_native.py",),
        "real_helper_simulated_build",
        "Owned test trees update or roll back and retain recovery data.",
        platforms=("darwin", "linux"),
        timeout_seconds=600,
    ),
    Scenario(
        "MAC-IDENTITY",
        "processes",
        "Control Center application identity",
        ("tests/native/macos/test_control_center_identity.py",),
        "real_source_window",
        "The settled child is Accessory; sampling also records transient identity.",
        platforms=("darwin",),
        observe_identity=True,
    ),
    Scenario(
        "BUNDLE-IDENTITY",
        "packaging",
        "Frozen inventory and source commit",
        (
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_frozen_bundle_carries_every_runtime_dependency",
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_frozen_bundle_was_built_from_the_expected_commit",
        ),
        "real_packaged_inventory",
        "All runtime assets exist and the stamp matches the requested commit.",
        needs_bundle=True,
    ),
    Scenario(
        "BUNDLE-WINDOW",
        "packaging",
        "Frozen Control Center window and bridge",
        (
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_frozen_control_center_opens_and_answers_its_own_page",
        ),
        "real_packaged_ui",
        "The shipped page renders, reaches the bridge and exits.",
        needs_bundle=True,
        timeout_seconds=660,
        observe_identity=True,
    ),
    Scenario(
        "BUNDLE-WORKER",
        "packaging",
        "Frozen providers on an isolated profile",
        (
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_frozen_worker_becomes_ready_on_an_isolated_profile",
        ),
        "real_packaged_fixture",
        "The frozen runtime recognizes the committed fixture and closes.",
        needs_bundle=True,
        timeout_seconds=1260,
    ),
    Scenario(
        "BUNDLE-LAUNCH-IDENTITY",
        "packaging",
        "Normal frozen launch, close, reactivation and tray reopen",
        ("tests/packaged/macos/test_frozen_identity.py",),
        "real_packaged_launch",
        "Only the shell is a Foreground app; children never are; all exit on quit.",
        platforms=("darwin",),
        needs_bundle=True,
        timeout_seconds=600,
    ),
    Scenario(
        "WINDOWS-UPDATE",
        "updater",
        "Complete Windows application update",
        (),
        "not_implemented",
        "Plan, download, helper, apply, relaunch, acknowledgement and cleanup.",
        platforms=("win32",),
    ),
    Scenario(
        "LIVE-HOVER",
        "hover_popup",
        "Real desktop hover and OCR fallback",
        (),
        "human_operated",
        "`python -m lab tour` drives real hovers over lab pages; private screens "
        "need a person and live-hover's explicit Export.",
    ),
    Scenario(
        "RESOURCE-DELIVERY",
        "resources",
        "Resource validation and atomic activation",
        ("tests/test_update_service.py", "tests/test_resource_manager.py"),
        "simulated_delivery_real_files",
        "Invalid resources refuse activation and the previous copy survives.",
    ),
)


def select_scenarios(ids: tuple[str, ...]) -> tuple[Scenario, ...]:
    """Resolve known unique IDs before starting any scenario."""

    catalog = {item.id: item for item in SCENARIOS}
    if not ids or len(set(ids)) != len(ids) or any(item not in catalog for item in ids):
        raise ValueError("select one or more unique scenario IDs from `python -m lab check list`")
    return tuple(catalog[item] for item in ids)
