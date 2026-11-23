
import subprocess
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path

from runner import presentation as ui
from runner.context import REPOSITORY_ROOT, format_command
from runner.presentation import output as print


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_visible_subprocess_output_pauses_progress
# @matrix setup : spinner subprocess-output
def run_command(
    command: Sequence[str | Path],
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
    timeout: float = 600,
    cwd: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess | subprocess.CalledProcessError:
    """Run a shell command and return the result."""
    try:
        with ui.pause_progress() if not capture_output else nullcontext():
            result = subprocess.run(
                command,
                capture_output=capture_output,
                text=text,
                check=check,
                timeout=timeout,
                cwd=cwd,
            )
        return result
    except subprocess.CalledProcessError as e:
        print(ui.error("Command failed"))
        print("  " + format_command(command))
        if e.stderr:
            print(e.stderr, raw=True)
        if check:
            raise RuntimeError(
                f"Command failed: {' '.join(str(part) for part in command)}"
            ) from e
        return e
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Command timed out after {timeout} seconds: "
            f"{' '.join(str(part) for part in command)}"
        ) from error
