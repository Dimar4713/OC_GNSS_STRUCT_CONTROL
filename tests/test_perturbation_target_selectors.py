from constellation_control.preview.perturbation_ui import PERTURBATION_CARD, PERTURBATION_SCRIPT


def test_perturbation_targets_use_catalog_selectors() -> None:
    assert 'class="pt" multiple' in PERTURBATION_SCRIPT
    assert "perturbationCatalog()" in PERTURBATION_SCRIPT
    assert "satellite:[...new Set" in PERTURBATION_SCRIPT
    assert "plane:[...new Set" in PERTURBATION_SCRIPT
    assert "group:[...new Set" in PERTURBATION_SCRIPT
    assert "ID через запятую" not in PERTURBATION_CARD + PERTURBATION_SCRIPT


def test_perturbation_targets_refresh_when_scenario_changes() -> None:
    assert "loadScenarioBeforePerturbationTargets=loadScenario" in PERTURBATION_SCRIPT
    assert "syncPerturbationTargets();" in PERTURBATION_SCRIPT
    assert "scope==='constellation'?[]" in PERTURBATION_SCRIPT
    assert "Select at least one target" in PERTURBATION_SCRIPT


def test_perturbation_scope_has_no_implicit_constellation_default() -> None:
    assert '<option value="">— выбрать область —</option><option value="constellation">' in PERTURBATION_SCRIPT
    assert "if(scope==='')" in PERTURBATION_SCRIPT
    assert "Select scope for every enabled row" in PERTURBATION_SCRIPT
    assert "явных M, закона распределения и области применения" in PERTURBATION_CARD
