"""Download public PaySim into this checkout without overwriting existing data."""
from pathlib import Path
import shutil
import kagglehub

ROOT = Path(__file__).resolve().parents[2]


def main():
    destination = ROOT / "data/raw/paysim.csv"
    if destination.exists():
        print(f"Using existing dataset: {destination}")
        return
    download_path = kagglehub.dataset_download(
        "moonknightmarvel/paysim", output_dir=str(ROOT / ".cache/paysim"),
    )
    candidates = list(Path(download_path).rglob("*.csv"))
    exact = [path for path in candidates if path.name.lower() == "paysim.csv"]
    choices = exact or candidates
    if len(choices) != 1:
        raise RuntimeError(f"Expected one transaction CSV, found {len(choices)} in {download_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(choices[0], destination)
    print(f"Dataset saved to {destination} ({destination.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
