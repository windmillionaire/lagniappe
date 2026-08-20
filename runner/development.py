import os
import subprocess
import sys

from config import SETTINGS, Environment, APP_DIR
from runner.gcloud import activate_repository_gcloud


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_aligns_adc_before_flask_launch
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_adc_mismatch_stops_before_flask
# @features development
# @dimensions gcloud-config adc launch-order noninteractive
def run_dev_server():
    try:
        activate_repository_gcloud(
            ensure_adc=True,
            allow_runtime_adc=True,
            allow_adc_login=False,
        )
    except RuntimeError as error:
        print(f"Development server startup stopped: {error}")
        return 1
    dev_settings = SETTINGS.dev_config
    env = os.environ.copy()
    env["FLASK_ENV"] = Environment.DEVELOPMENT.value
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flask",
            "--app",
            "main.py",
            "--debug",
            "run",
            "--port",
            dev_settings["SERVER_PORT"],
        ],
        env=env,
        cwd=APP_DIR,
        timeout=900,
    )
    return result.returncode
