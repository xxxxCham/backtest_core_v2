from utils.parameters import (
    ParameterSpec,
    compute_search_space_stats,
    normalize_param_grid_values,
    normalize_param_ranges,
)


def test_normalize_param_ranges_clamps_and_counts():
    specs = {
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=0.5,
            max_val=4.0,
            default=1.5,
            step=0.5,
            param_type="float",
        )
    }
    ranges = {
        "k_sl": {"min": 0.0, "max": 2.0, "step": 0.5},
    }

    normalized, warnings = normalize_param_ranges(specs, ranges)

    assert normalized["k_sl"]["min"] == 0.5
    assert normalized["k_sl"]["values"][0] == 0.5
    assert len(normalized["k_sl"]["values"]) == normalized["k_sl"]["count"]
    assert warnings

    stats = compute_search_space_stats(normalized)
    assert stats.per_param_counts["k_sl"] == len(normalized["k_sl"]["values"])


def test_normalize_param_grid_values_filters_out_of_bounds():
    specs = {
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=0.5,
            max_val=4.0,
            default=1.5,
            step=0.5,
            param_type="float",
        )
    }
    grid = {"k_sl": [0.0, 0.5, 1.0, 5.0]}

    normalized, warnings = normalize_param_grid_values(specs, grid)

    assert normalized["k_sl"] == [0.5, 1.0]
    assert warnings
