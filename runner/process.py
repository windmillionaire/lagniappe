import subprocess

from runner.context import REPOSITORY_ROOT


# @testable false
# @reason shared subprocess adapter is exercised by owning deployment workflows
def run_command(
    command,
    check=True,
    capture_output=True,
    text=True,
    timeout=600,
    cwd=REPOSITORY_ROOT,
):
    """Run a shell command and return the result."""
    try:
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
        print(f"Error running command: {' '.join(str(part) for part in command)}")
        if e.stderr:
            print(f"Error: {e.stderr}")
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
