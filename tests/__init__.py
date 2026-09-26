"""Test suite for the AvP RIF Importer add-on.

How to run (from Blender's Python console, because importing avp_rif_importer
triggers `import bpy` through the package __init__):

    import sys
    sys.path.insert(0, r"C:\\Users\\aschw\\AppData\\Roaming\\Blender Foundation\\Blender\\5.2\\scripts\\addons")
    from avp_rif_importer.tests import run_all
    run_all()

Individual test modules can be run the same way:

    python -m unittest avp_rif_importer.tests.test_huffman

Only stdlib `unittest` is required - no pytest dependency.
"""

from __future__ import annotations

import os
import sys
import unittest


def run_all(verbosity: int = 2):
    """Discover and run every test_*.py under this directory.

    Sets up sys.path so `avp_rif_importer` is importable, then delegates to
    unittest's standard discovery machinery with top_level_dir set to the
    addons directory (so test modules load as avp_rif_importer.tests.*).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    addon_parent = os.path.dirname(os.path.dirname(here))
    if addon_parent not in sys.path:
        sys.path.insert(0, addon_parent)

    loader = unittest.TestLoader()
    suite = loader.discover(here, pattern="test_*.py",
                            top_level_dir=addon_parent)
    runner = unittest.TextTestRunner(verbosity=verbosity)
    return runner.run(suite)