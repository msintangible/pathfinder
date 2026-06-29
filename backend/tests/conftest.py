import sys
from pathlib import Path

# Make the backend package importable when running pytest from any directory.
sys.path.insert(0, str(Path(__file__).parent.parent))
