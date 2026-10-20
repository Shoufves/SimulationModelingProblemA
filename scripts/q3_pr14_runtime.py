"""Load the pinned PR14 package in a dedicated interpreter, never mix Q2s."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT/'vendor/q2_pr14'
if 'energy_model' in sys.modules:
    raise RuntimeError('PR14 runtime requires a fresh interpreter')
sys.path[:0] = [str(VENDOR/'src'), str(VENDOR/'scripts'), str(ROOT/'src')]
import energy_model
energy_model.__path__.append(str(ROOT/'src/energy_model'))
from q2_delivery_snapshot import decode, build_snapshot
from energy_model.q2_forward_current import activate_forward
from run_q2_portable import compare_reference
from run_q2_national import targets
# The legacy experiment driver is imported by file name from the main scripts.
sys.path.insert(0, str(ROOT/'scripts'))
