"""Worker-local cache of immutable parsed evidence for a frozen experiment.

Every return is deep-copied. No parameters, model state, prices derived from
parameters, candidate scores or outputs are cached. Parent runners must also
verify the same source hashes after training and evaluation.
"""
from copy import deepcopy
from functools import lru_cache,wraps
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def install(source_hashes):
    if not source_hashes or any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h for p,h in source_hashes.items()):
        raise ValueError("Input cache requires verified frozen experiment sources")
    import run_q2_empirical_support as empirical
    import build_q2_electricity_scope as electricity
    import build_q2_project_costs as costs
    targets = (empirical.fiscal_observations,empirical.cec_tables,electricity.extract,costs.extract)
    bindings = []
    caches = []
    for original in targets:
        cached = lru_cache(maxsize=8)(original)
        def wrapped(*args,_cached=cached,**kwargs):
            return deepcopy(_cached(*args,**kwargs))
        wraps(original)(wrapped)
        caches.append(cached)
        # These are aliases of the exact pure reader, not name-based replacements.
        for module in tuple(sys.modules.values()):
            name = getattr(module,"__name__","")
            if not name.startswith(("run_q2_","q2_","build_q2_")):
                continue
            for key,value in list(vars(module).items()):
                if value is original:
                    bindings.append((module,key,original))
                    setattr(module,key,wrapped)
    def restore():
        for module,key,original in reversed(bindings):
            setattr(module,key,original)
        for cached in caches:
            cached.cache_clear()
    return restore
