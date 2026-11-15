import importlib
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class LocalWeatherImportTest(unittest.TestCase):
    def test_local_weather_widget_module_imports(self) -> None:
        sys.modules.pop("core.widgets.yasb.local_weather", None)

        module = importlib.import_module("core.widgets.yasb.local_weather")

        self.assertTrue(hasattr(module, "LocalWeatherWidget"))


if __name__ == "__main__":
    unittest.main()
