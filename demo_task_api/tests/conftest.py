"""Test configuration for demo_task_api.

Adds project root to import path so `app` package imports are stable in local runs.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
