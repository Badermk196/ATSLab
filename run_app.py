"""
Start the app (app.py) with the Streamlit fix applied before the server starts (streamlit_fix.py).

  py -3.12 run_app.py --server.port 8501 --server.headless true --server.address 127.0.0.1

Any Streamlit option can follow; it is the same as "streamlit run app.py <options>".
"""

import os
import sys

import streamlit_fix

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    streamlit_fix.apply()
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", os.path.join(HERE, "app.py"), *sys.argv[1:]]
    sys.exit(cli.main())
