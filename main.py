"""
Entry point — launches the Stock Analyzer backend (FastAPI + uvicorn).

    python main.py     # serve API on http://localhost:10000  (docs at /docs)

The Angular client runs separately (cd frontend && npm start) on port 6000.
"""
import os
import sys

# make the project root + backend package importable before importing the app
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn
from backend.api import app  # FastAPI app — transitively imports analyzer + ticker_finder

# host/port overridable from the environment (defaults match the frontend config)
HOST = os.environ.get("API_HOST", "0.0.0.0")
PORT = int(os.environ.get("API_PORT", "10000"))


if __name__ == "__main__":
    print(f"Starting Stock Analyzer API on http://localhost:{PORT}  (docs at /docs)")
    print("Frontend: cd frontend && npm start   -> http://localhost:6000")
    uvicorn.run(app, host=HOST, port=PORT)
