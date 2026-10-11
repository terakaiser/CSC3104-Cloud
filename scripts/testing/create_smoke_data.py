"""Create artificial execution fixtures in a separate, new directory."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from crossbank.data.smoke import create_smoke_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/smoke"))
    parser.add_argument("--rows", type=int, default=256)
    args = parser.parse_args()
    create_smoke_data(args.output_dir, args.rows)
    print(f"Created synthetic smoke fixtures in {args.output_dir}; these are not benchmark data.")
