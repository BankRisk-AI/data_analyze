import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = PROJECT_ROOT / "scripts" / "validate_memory.py"


def test_memory_validation():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    output = result.stdout + result.stderr

    assert result.returncode == 0, (
        f"Memory validation failed:\n{output}"
    )
    assert "SUCCESS: memory structure is valid." in output
