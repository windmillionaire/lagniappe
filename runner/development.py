import os
import signal
import subprocess
import sys

from config import SETTINGS, Environment, APP_DIR
from runner.gcloud import activate_repository_gcloud


# @testable false
# @covered-by runner/development.py::run_dev_server
# @reason signal forwarding is exercised through the foreground dev-server owner
def _forward_signal_to_process_group(process, signum):
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


# @testable false
# @covered-by runner/development.py::run_dev_server
# @reason exceptional cleanup is exercised through the foreground dev-server owner
def _stop_process_group(process):
    if process.poll() is not None:
        return
    _forward_signal_to_process_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _forward_signal_to_process_group(process, signal.SIGKILL)
        process.wait()


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_aligns_adc_before_flask_launch
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_adc_mismatch_stops_before_flask
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_forwards_signals_and_restores_handlers
# @tests tests_tooling/test_007_run_py_test_command.py::test_run_dev_server_cleans_up_process_group_after_runner_failure
# @matrix development : adc escalation exceptional-cleanup gcloud-config launch-order lifecycle noninteractive process-ownership signals
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
    process = subprocess.Popen(
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
        start_new_session=True,
    )
    previous_handlers = {}
    completed = False

    def forward_signal(signum, frame):
        _forward_signal_to_process_group(process, signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_signal)
        return_code = process.wait()
        completed = True
        return return_code
    finally:
        if not completed:
            _stop_process_group(process)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
