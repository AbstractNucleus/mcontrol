"""Dev entry point: ``python -m mcontrol``.

Binds to ``$PORT`` when the preview harness assigns one (autoPort); the
uvicorn CLI has no way to read that env var, so it is bridged here.
Falls back to 8000 for a plain manual run.
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "mcontrol.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
