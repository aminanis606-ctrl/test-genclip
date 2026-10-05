import sys
from pathlib import Path

_APP_PYTHON = Path(__file__).resolve().parent / "app" / "src" / "main" / "python"
if str(_APP_PYTHON) not in sys.path:
    sys.path.insert(0, str(_APP_PYTHON))

from audio_analysis import *
