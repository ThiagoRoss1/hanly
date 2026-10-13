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
        "Packaged desktop readiness and shutdown",
        (
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_native_window_waits_for_react_and_answers_its_state_bridge",
        ),
        "real_packaged_app",
        "The native root waits for React and its service, then exits cleanly.",
        needs_bundle=True,
        timeout_seconds=480,
        observe_identity=True,
    ),
    Scenario(
        "CC-LIFECYCLE",
        "control_center",
        "React window routes and event readiness",
        ("apps/desktop/tests/ui/desktop-pages.test.tsx",),
        "react_dom_mock_ipc",
        "Popup and region routes wait for their native event listeners before ready.",
    ),
    Scenario(
        "CC-CONTROLS",
        "control_center",
        "Settings and service-backed controls",
        ("apps/desktop/tests/ui/desktop-pages.test.tsx",),
        "react_dom_mock_ipc",
        "Settings persist through the desktop service and failures stay visible.",
    ),
    Scenario(
        "CC-UPDATE-STAGE",
        "updater_ui",
        "Update confirmation, progress and activity controls",
        ("apps/desktop/tests/ui/desktop-pages.test.tsx",),
        "react_dom_jsdom_mock_ipc",
        (
            "The React update page confirms a full download and renders acknowledged "
            "progress and activity."
        ),
    ),
    Scenario(
        "CAPTURE-CHOICE",
        "capture",
        "Capture-scope dialog cancellation",
        ("apps/desktop/tests/ui/desktop-pages.test.tsx",),
        "react_dom_mock_ipc",
        "Cancelling the capture-scope dialog leaves capture settings unchanged.",
    ),
    Scenario(
        "HOVER-POPUP",
        "hover_popup",
        "Popup route and request currency",
        ("apps/desktop/tests/ui/desktop-pages.test.tsx",),
        "react_dom_mock_ipc",
        "Only current dictionary events render, and popup actions report geometry.",
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
        "Packaged native application identity",
        (
            "tests/packaged/macos/test_frozen_identity.py::"
            "test_the_tauri_root_is_the_only_foreground_app_and_owns_the_service",
        ),
        "real_packaged_app_identity",
        "The Tauri root is foreground and owns the Python service and WebKit family.",
        platforms=("darwin",),
        needs_bundle=True,
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
            "test_the_native_window_waits_for_react_and_answers_its_state_bridge",
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
        "Frozen OCR runtime on an isolated profile",
        (
            "tests/packaged/shared/test_packaged_desktop.py::"
            "test_the_frozen_ocr_self_check_runs_on_an_isolated_profile",
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
        "The Tauri root is foreground; its service and WebKit family exit on quit.",
        platforms=("darwin",),
        needs_bundle=True,
        timeout_seconds=600,
    ),
    Scenario(
        "BUNDLE-LAUNCH-IDENTITY-WIN",
        "packaging",
        "Normal frozen launch, capture, close, tray reopen and quit on Windows",
        ("tests/packaged/windows/test_frozen_identity.py",),
        "real_packaged_launch",
        "The Tauri root owns the taskbar window; its service exits on quit.",
        platforms=("win32",),
        needs_bundle=True,
        timeout_seconds=600,
    ),
    Scenario(
        "WINDOWS-UPDATE",
        "updater",
        "Complete Windows application update (`python -m lab check windows-update`)",
        (),
        "real_release_real_helper_checkout_updater",
        "Plan, download, helper, apply, relaunch, acknowledgement and cleanup; cancel and "
        "rollback as separate modes. Network-bound, so it is its own command.",
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
