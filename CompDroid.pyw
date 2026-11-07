"""Double-click to open CompDroid on Windows (no install or PATH setup needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "builder"))

from compdroid.gui import main  # noqa: E402

main()
