"""Repository checkout entry point for the local WorkBuddy Worker MCP."""

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'src'))

from grokbuddy.interfaces.worker_mcp import main  # noqa: E402


if __name__ == '__main__':
    main()
