"""PR14's uniform national scaling, with the explicit rolling-event LP."""
from copy import deepcopy
from .operations import operate


def operate_national(operation):
    scale = 1000.0
    def scaled(obj):
        result = {}
        for k, v in obj.items():
            if isinstance(v, dict):
                result[k] = scaled(v)
            elif (k.endswith(("_mwh", "_mw")) and "_per_" not in k) or k in {"ramp_mw_per_hour", "budget_cny"}:
                result[k] = [x/scale for x in v] if isinstance(v, list) else v/scale
            else:
                result[k] = deepcopy(v)
        return result
    result = operate(scaled(operation))
    for key in ("resource_cost", "max_residual", "dispatch_objective", "policy_signal_cost"):
        result[key] *= scale
    for key in ("actual_dispatch_cost", "behavioral_score", "reference_fossil_mwh"):
        if result.get(key) is not None:
            result[key] *= scale
    for group in ("fuel", "generation", "demand", "storage", "additional_storage", "recoveries", "balances", "stages"):
        for row in result[group]:
            for key, value in list(row.items()):
                if key.endswith(("_mwh", "_co2_t")) or key in {"residual", "objective", "max_residual"}:
                    row[key] = value*scale
    return result
