"""Stage the application code needed by a Flower runtime."""

import shutil
from pathlib import Path


def stage_bundle(output: Path, source: Path = Path(".")):
    package = output / "package"
    package.mkdir()
    shutil.copy(source / "pyproject.toml", package)
    # Flower 1.22 matches ignore rules against absolute paths. Copying the root
    # "results/" rule here would exclude the entire staged bundle.
    (package / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for name in ("app", "experiments"):
        shutil.copytree(source / name, package / name, ignore=shutil.ignore_patterns("__pycache__"))
    return package
