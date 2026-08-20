import inspect
import os


def get_test_info():
    """
    Returns test function name and filename.

    Args:
        include_path: If True, returns full path instead of just filename

    Returns:
        tuple: (test_function_name, test_file)
    """
    frame = inspect.currentframe().f_back
    function_name = frame.f_code.co_name
    full_path = frame.f_code.co_filename

    return os.path.basename(full_path), function_name
