"""Put the backend package on the import path for tests.

Tests run from the repository root; the application lives in backend/. Without
this every test file would need its own sys.path juggling.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))
