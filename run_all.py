"""Single-laptop development launcher: all five database services + Gateway + Streamlit.

Equivalent to `python start_node.py all`. Databases are initialized NON-destructively
(existing records and accepted cleansing changes are kept). To start from clean seed
data run `python start_node.py init all --reset` first (a backup is taken automatically).
"""
import sys

import start_node

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "all"] + sys.argv[1:]
    start_node.main()
