from __future__ import annotations

import json
from pathlib import Path

from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app.updates.desktop_runtime import (
    UpdateCompositionError,
    load_update_service,
)
from hanly_app.updates.resource_service import UpdateService


def test_update_service_uses_optional_github_configuration(tmp_path: Path) -> None:
    resource = tmp_path / "resource.bin"
    resource.write_bytes(b"resource")
    manager = ResourceManager(ResourceManifest((ResourceSpec("resource", resource),)))
    manager.validate()
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "updates": {
                    "github": {
                        "owner": "acme",
                        "repository": "hanly",
                        "manifest_asset": "resources.json",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert isinstance(load_update_service(config, manager), UpdateService)
    config.write_text("{}", encoding="utf-8")
    assert load_update_service(config, manager) is None


def test_invalid_update_configuration_raises_a_composition_error(tmp_path: Path) -> None:
    manager = ResourceManager(ResourceManifest(()))
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"updates": []}), encoding="utf-8")

    try:
        load_update_service(config, manager)
    except UpdateCompositionError as error:
        assert "updates must be a JSON object" in str(error)
    else:
        raise AssertionError("invalid update configuration must be refused")
