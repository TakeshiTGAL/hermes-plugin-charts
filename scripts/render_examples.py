"""Re-render the README images in docs/examples from tests/examples.py.

Run after any change to how charts look, so the README never shows an older
drawing:  python scripts/render_examples.py
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import examples  # noqa: E402
from helpers import load_plugin  # noqa: E402

TARGETS = {"POPULATION_TOP10": "population_top10.png", "MONTHLY_SALES": "monthly_sales.png",
           "SALES_MIX": "sales_mix.png"}


def main() -> int:
    plugin = load_plugin()
    out_dir = ROOT / "docs" / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, filename in TARGETS.items():
        result = json.loads(plugin.tools.chart_render(getattr(examples, name)))
        if not result.get("success"):
            print(f"{name}: {result['error']}", file=sys.stderr)
            return 1
        shutil.copyfile(result["path"], out_dir / filename)
        print(f"{filename}: {result['chart']['size_px']} verification={result['verification']['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
