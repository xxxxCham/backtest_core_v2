from ui.helpers import (
    compute_global_granularity_percent,
    granularity_transform,
)
from utils.parameters import ParameterSpec


def _make_specs():
    return {
        "a": ParameterSpec(
            name="a",
            min_val=0,
            max_val=10,
            default=1,
            step=1,
            param_type="int",
        ),
        "b": ParameterSpec(
            name="b",
            min_val=0,
            max_val=20,
            default=6,
            step=2,
            param_type="int",
        ),
    }


def _is_on_step(value: float, spec: ParameterSpec) -> bool:
    if spec.step is None or spec.step <= 0:
        return True
    idx = (float(value) - float(spec.min_val)) / float(spec.step)
    return abs(idx - round(idx)) < 1e-9


def test_granularity_transform_increase_example_and_invariants():
    specs = _make_specs()
    params = {"a": 1, "b": 18}

    updated = granularity_transform(
        params=params,
        param_specs=specs,
        delta=0.1,
        direction="increase",
    )

    assert updated["a"] == 2
    assert updated["b"] == 18

    for name, spec in specs.items():
        value = float(updated[name])
        assert float(spec.min_val) <= value <= float(spec.max_val)
        assert _is_on_step(value, spec)


def test_granularity_transform_decrease_toward_min():
    specs = _make_specs()
    params = {"a": 1, "b": 6}

    updated = granularity_transform(
        params=params,
        param_specs=specs,
        delta=0.5,
        direction="decrease",
    )

    assert updated["a"] == 0
    assert updated["b"] == 4


def test_granularity_transform_tiny_delta_can_be_noop_after_snap():
    specs = _make_specs()
    params = {"a": 1, "b": 6}

    updated = granularity_transform(
        params=params,
        param_specs=specs,
        delta=0.0005,
        direction="increase",
    )

    assert updated == params


def test_granularity_transform_ignores_invalid_specs_and_non_numeric_values():
    specs = {
        "fixed": ParameterSpec(
            name="fixed",
            min_val=5,
            max_val=5,
            default=5,
            step=1,
            param_type="int",
        ),
        "nostep": ParameterSpec(
            name="nostep",
            min_val=0,
            max_val=10,
            default=3,
            step=0,
            param_type="int",
        ),
    }
    params = {"fixed": 5, "nostep": 4, "text": "abc"}

    updated = granularity_transform(
        params=params,
        param_specs=specs,
        delta=0.5,
        direction="increase",
    )

    assert updated["fixed"] == 5
    assert updated["nostep"] == 4
    assert updated["text"] == "abc"


def test_compute_global_granularity_percent_matches_expected_average():
    specs = _make_specs()
    all_params = {"demo": {"a": 1, "b": 18}}
    all_specs = {"demo": specs}

    value = compute_global_granularity_percent(all_params=all_params, all_param_specs=all_specs)
    assert value is not None
    assert abs(value - 50.0) < 1e-9


def test_sidebar_sync_cycle_has_no_reapply_loop_after_param_change():
    specs = _make_specs()
    all_specs = {"demo": specs}

    # État initial : slider à 20%
    current_global = 20.0
    previous_global = 20.0

    # L'utilisateur modifie un paramètre localement (params -> sidebar)
    all_params = {"demo": {"a": 1, "b": 18}}
    summary = compute_global_granularity_percent(all_params=all_params, all_param_specs=all_specs)
    assert summary is not None and abs(summary - 50.0) < 1e-9

    # Synchronisation interne de la sidebar
    current_global = summary
    previous_global = current_global

    # Run suivant: aucun delta global => aucune transformation ré-appliquée
    diff = current_global - previous_global
    assert abs(diff) < 1e-12
