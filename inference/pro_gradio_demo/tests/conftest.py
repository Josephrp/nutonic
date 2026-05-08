import sys
from pathlib import Path


def pytest_configure() -> None:
    # Allow running `pytest inference/pro_gradio_demo/tests` without installing the package.
    repo_root = Path(__file__).resolve().parents[3]
    src_dir = repo_root / "inference" / "pro_gradio_demo" / "src"
    sys.path.insert(0, str(src_dir))

