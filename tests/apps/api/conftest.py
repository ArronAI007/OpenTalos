import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent.parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))
