"""
conftest.py – Shared test configuration and helpers.

Uses importlib.util.spec_from_file_location to load each Lambda handler
by its absolute file path, avoiding Python module-name collisions
(all handlers are named 'handler').
"""

import importlib.util
import os
import sys
import types


SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))


def load_handler(subdir: str) -> types.ModuleType:
    """
    Load a Lambda handler module by absolute file path.

    :param subdir: sub-directory name inside src/ (e.g. 'upload_handler')
    :return: loaded module object
    """
    module_name = f"_handler_{subdir}"
    # Remove any previously cached version so env-var changes take effect
    sys.modules.pop(module_name, None)

    file_path = os.path.join(SRC_DIR, subdir, "handler.py")
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
