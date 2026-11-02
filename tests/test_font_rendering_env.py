""".env handling and the YASB_FONT_ANTIALIAS / YASB_FONT_HINTING switches.

A reload starts the new YASB process with the old one's environment, so `.env` has to win over
inherited values or an edited setting never takes effect. The two font switches land on the
application font, which stylesheet fonts inherit everything but family, size and weight from.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

_instance = QApplication.instance()
APP = _instance if isinstance(_instance, QApplication) else QApplication([])

import env  # noqa: E402

KEYS = ("YASB_FONT_ENGINE", "YASB_FONT_ANTIALIAS", "YASB_FONT_HINTING")


class EnvIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in KEYS}
        self._app_font = QFont(APP.font())
        for k in KEYS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        APP.setFont(self._app_font)


class LoadEnvTest(EnvIsolation):
    def test_env_file_wins_over_an_inherited_value(self) -> None:
        """A reload inherits YASB_FONT_ENGINE=freetype; the edited .env says native."""
        os.environ["YASB_FONT_ENGINE"] = "freetype"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("YASB_FONT_ENGINE=native\n", encoding="utf-8")
            with patch.object(env, "get_env_path", return_value=str(path)):
                env.load_env()
        self.assertEqual(os.environ["YASB_FONT_ENGINE"], "native")

    def test_missing_file_leaves_the_environment_alone(self) -> None:
        os.environ["YASB_FONT_ENGINE"] = "gdi"
        with patch.object(env, "get_env_path", return_value=str(Path(tempfile.gettempdir()) / "no-such.env")):
            env.load_env()
        self.assertEqual(os.environ["YASB_FONT_ENGINE"], "gdi")


class FontRenderingOptionsTest(EnvIsolation):
    def test_defaults(self) -> None:
        self.assertEqual(env.font_rendering_options(), ("subpixel", "default"))

    def test_values_are_case_and_space_insensitive(self) -> None:
        os.environ["YASB_FONT_ANTIALIAS"] = " Grayscale "
        os.environ["YASB_FONT_HINTING"] = "VERTICAL"
        self.assertEqual(env.font_rendering_options(), ("grayscale", "vertical"))

    def test_unknown_values_fall_back_to_the_defaults(self) -> None:
        os.environ["YASB_FONT_ANTIALIAS"] = "cleartype"
        os.environ["YASB_FONT_HINTING"] = "slight"
        with self.assertLogs(level="WARNING"):
            self.assertEqual(env.font_rendering_options(), ("subpixel", "default"))


class ApplyFontRenderingTest(EnvIsolation):
    def test_unset_leaves_the_application_font_untouched(self) -> None:
        before = QFont(APP.font())
        env.apply_font_rendering(APP)
        self.assertEqual(APP.font(), before)

    def test_grayscale_and_hinting_land_on_the_application_font(self) -> None:
        os.environ["YASB_FONT_ANTIALIAS"] = "grayscale"
        os.environ["YASB_FONT_HINTING"] = "none"
        env.apply_font_rendering(APP)
        font = APP.font()
        self.assertTrue(font.styleStrategy() & QFont.StyleStrategy.NoSubpixelAntialias)
        self.assertEqual(font.hintingPreference(), QFont.HintingPreference.PreferNoHinting)

    def test_stylesheet_fonts_inherit_them(self) -> None:
        os.environ["YASB_FONT_ANTIALIAS"] = "grayscale"
        env.apply_font_rendering(APP)
        label = QLabel("Thu 29 12:37")
        label.setStyleSheet("font-family: 'Segoe UI'; font-size: 12px; font-weight: 600;")
        label.ensurePolished()
        self.assertEqual(label.font().family(), "Segoe UI")
        self.assertTrue(label.font().styleStrategy() & QFont.StyleStrategy.NoSubpixelAntialias)


GDI_PROBE = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, sys.argv[1])
    from PyQt6.QtWidgets import QApplication, QLabel
    import env
    app = QApplication([])
    env.apply_font_rendering(app)
    label = QLabel("Thu 29 12:37  Asr 14:53")
    label.setStyleSheet("font-family: 'Segoe UI'; font-size: 12px; font-weight: 600; color: #ffffff; background: #303030;")
    label.adjustSize()
    image = label.grab().toImage()
    fringe = 0
    for x in range(image.width()):
        for y in range(image.height()):
            c = image.pixelColor(x, y)
            if max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 30:
                fringe += 1
    print(fringe)
    """
)


@unittest.skipUnless(sys.platform == "win32", "GDI is Windows-only")
class GrayscaleUnderGdiTest(unittest.TestCase):
    """The engine is fixed when QApplication starts, so each case runs in its own process."""

    def fringe_pixels(self, antialias: str | None) -> int:
        child_env = {k: v for k, v in os.environ.items() if k not in KEYS}
        child_env["QT_QPA_PLATFORM"] = "windows:fontengine=gdi"
        if antialias:
            child_env["YASB_FONT_ANTIALIAS"] = antialias
        out = subprocess.run(
            [sys.executable, "-c", GDI_PROBE, str(SRC_ROOT)],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return int(out.stdout.strip().splitlines()[-1])

    def test_grayscale_removes_the_colour_fringes(self) -> None:
        if self.fringe_pixels(None) == 0:
            self.skipTest("this system draws without ClearType, so there is nothing to remove")
        self.assertEqual(self.fringe_pixels("grayscale"), 0)


if __name__ == "__main__":
    unittest.main()
