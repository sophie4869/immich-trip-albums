import os
import sys

# Ensure the repo root is importable when running tests without an editable install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
