"""``uvicorn`` entry for Hugging Face Docker Space (port ``PORT`` / 7860)."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from nutonic_terramind_tim_local.space_api import app

    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
