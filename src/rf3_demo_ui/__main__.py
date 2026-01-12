from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("rf3_demo_ui.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
