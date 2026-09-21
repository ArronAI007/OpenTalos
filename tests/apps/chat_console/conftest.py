import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "apps" / "chat_console"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
