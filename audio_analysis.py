import importlib.util
import sys
from pathlib import Path

_APP_AUDIO_ANALYSIS = Path(__file__).resolve().parent / "app" / "src" / "main" / "python" / "audio_analysis.py"

spec = importlib.util.spec_from_file_location("_app_audio_analysis", _APP_AUDIO_ANALYSIS)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

for _attr in getattr(_mod, "__all__", [k for k in _mod.__dict__ if not k.startswith("__")]):
    globals()[_attr] = getattr(_mod, _attr)
