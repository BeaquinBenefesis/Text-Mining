"""Development runner for the knowledgebase UI.

    python scripts/web/run_ui.py            # http://127.0.0.1:8000
    python scripts/web/run_ui.py --port 9000 --host 0.0.0.0

The database is opened read-only and immutable, so the server can never modify it.
"""
import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on source changes")
    args = parser.parse_args()
    uvicorn.run("textmining.web.app:app", host=args.host, port=args.port, reload=args.reload)
