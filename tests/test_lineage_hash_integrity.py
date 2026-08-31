from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.domain.digital_twin import ScenarioLineage


VALID_SHA = "0123456789abcdef" * 4


def test_valid_parent_hash_auto_enables_integrity_v1() -> None:
    lineage = ScenarioLineage(
        parent_scenario_id="parent",
        parent_config_hash=VALID_SHA,
        transformation="manual_edit",
    )
    assert lineage.integrity_version == 1


def test_legacy_non_structural_parent_hash_remains_readable() -> None:
    lineage = ScenarioLineage(
        parent_scenario_id="legacy-parent",
        parent_config_hash="legacy-hash-token",
        transformation="manual_edit",
    )
    assert lineage.integrity_version is None
    assert lineage.parent_config_hash == "legacy-hash-token"


def test_explicit_integrity_v1_rejects_non_sha256_parent_hash() -> None:
    with pytest.raises(ValidationError, match="integrity_version=1 requires parent_config_hash"):
        ScenarioLineage(
            parent_scenario_id="parent",
            parent_config_hash="not-a-sha256",
            integrity_version=1,
            transformation="manual_edit",
        )


def test_explicit_integrity_v1_accepts_valid_parent_hash() -> None:
    lineage = ScenarioLineage(
        parent_scenario_id="parent",
        parent_config_hash=VALID_SHA,
        integrity_version=1,
        transformation="manual_edit",
    )
    assert lineage.integrity_version == 1
