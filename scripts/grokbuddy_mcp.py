"""Repository checkout entry point for the WorkBuddy stdio MCP server."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grokbuddy.interfaces.mcp import main  # noqa: E402


if __name__ == "__main__":
    main()
