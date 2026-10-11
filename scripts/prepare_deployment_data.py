"""Copy prepared CSVs into separate mount folders for the four deployment roles."""
import argparse
from pathlib import Path
import shutil


def prepare(source: Path, destination: Path):
    files = {"coordinator": "validation.csv", "bank-a": "bank_a.csv",
             "bank-b": "bank_b.csv", "bank-c": "bank_c.csv"}
    for filename in files.values():
        if not (source / filename).is_file():
            raise FileNotFoundError(f"Missing {source / filename}; prepare data first")
    # Never mix a new dataset into a previously staged deployment.
    destination.mkdir(parents=True, exist_ok=False)
    for role, filename in files.items():
        folder = destination / role
        folder.mkdir()
        shutil.copy2(source / filename, folder / filename)
        marker = source / "SYNTHETIC_SMOKE_ONLY.txt"
        if marker.is_file():
            shutil.copy2(marker, folder / marker.name)
    print(f"Prepared separate bank and validation folders in {destination.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/smoke"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/deployment"))
    args = parser.parse_args()
    prepare(args.data_dir, args.output_dir)
