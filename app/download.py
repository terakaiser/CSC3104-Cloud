"""Download the pinned public ULB benchmark and prepare bank partitions."""

import hashlib
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from app.data import prepare, read_manifest

DATASET_URL = "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud"
DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/mlg-ulb/creditcardfraud?datasetVersionNumber=3"
)
# Fingerprint of creditcard.csv from the official version-3 download.
CSV_SHA256 = "76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_csv(path: Path):
    if sha256(path) != CSV_SHA256:
        raise ValueError(
            f"{path} does not match the pinned ULB dataset. "
            "Choose a different --raw directory or inspect the existing file; "
            "it was not overwritten."
        )


def download_csv(raw: Path) -> Path:
    target = raw / "creditcard.csv"
    if target.exists():
        verify_csv(target)
        print(f"Using verified dataset: {target.resolve()}", flush=True)
        return target
    raw.mkdir(parents=True, exist_ok=True)
    print("Downloading ULB credit-card dataset v3 from Kaggle (about 69 MB)...", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".ulb-", dir=raw) as temporary:
            archive = Path(temporary) / "dataset.zip"
            with urllib.request.urlopen(DOWNLOAD_URL, timeout=60) as source:
                with archive.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            # Extract only the expected file, never arbitrary archive paths.
            candidate = Path(temporary) / "creditcard.csv"
            with zipfile.ZipFile(archive) as bundle:
                with bundle.open("creditcard.csv") as source, candidate.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            verify_csv(candidate)
            if target.exists():
                verify_csv(target)
            else:
                candidate.rename(target)
    except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(
            "Dataset download failed. Check your connection or retry later. "
            f"You can download creditcard.csv from {DATASET_URL} and place it at {target}. "
            "If Kaggle requires login or consent, complete that on its website."
        ) from exc
    print(f"Verified dataset: {target.resolve()}", flush=True)
    return target


def setup_data(raw: Path, output: Path, *, banks: int = 3, seed: int = 42):
    if not 2 <= banks <= 10:
        raise ValueError("banks must be between 2 and 10")
    existing = None
    if output.exists() and any(output.iterdir()):
        if not (output / "manifest.json").is_file():
            raise ValueError(f"{output} is not empty; choose a different --output directory")
        existing = read_manifest(output)
        expected = {
            "schema": 1,
            "synthetic": False,
            "sha256": CSV_SHA256,
            "banks": banks,
            "seed": seed,
        }
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ValueError(
                f"{output} contains different data or settings; "
                "choose a different --output directory"
            )
        required = [output / f"bank-{i}" / "train.npz" for i in range(1, banks + 1)]
        required += [
            output / "evaluation" / f"{split}-bank-{i}.npz"
            for split in ("validation", "test")
            for i in range(1, banks + 1)
        ]
        if not all(path.is_file() for path in required):
            raise ValueError(f"{output} is incomplete; choose a fresh --output directory")
    csv = download_csv(raw)
    if existing is not None:
        print(f"Using existing prepared partitions: {output.resolve()}", flush=True)
        return existing
    # Prepare in a temporary sibling so interruption cannot publish partial partitions.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ulb-prepare-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "partitions"
        result = prepare(candidate, csv=csv, banks=banks, seed=seed)
        if output.exists():
            output.rmdir()  # Only an empty directory can be removed here.
        candidate.rename(output)
    print(f"Prepared real ULB partitions: {output.resolve()}", flush=True)
    return result
