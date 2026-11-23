"""Sign in to Comdia with the run's account and say whether it worked. Presses nothing else.

    COMDIA_USER=... COMDIA_PASSWORD=... python3 tools/comdia_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsource import comdia  # noqa: E402

if __name__ == "__main__":
    sys.exit(comdia.main(["--check"]))
