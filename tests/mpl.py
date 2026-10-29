"""Skip drawing checks when the declared matplotlib packages are absent."""
import importlib.util

import pytest

needs_matplotlib = pytest.mark.skipif(
    importlib.util.find_spec("matplotlib") is None,
    reason=(
        "plugin.yaml は matplotlib>=3.8,<4 と matplotlib-fontja>=1.0,<2 を宣言している。"
        "この実行環境には入っていない。Hermes の enable が入れる。"
        "無いあいだ chart_render は missing_dependency を返し、検証の文言には進まない。"
    ),
)
