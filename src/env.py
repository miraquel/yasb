import logging
import os
from collections.abc import Mapping

from dotenv import load_dotenv
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from settings import DEFAULT_CONFIG_DIRECTORY

# YASB_FONT_ANTIALIAS: "grayscale" smooths glyph edges in plain grey; "subpixel" (or unset) keeps the
# system's ClearType colour fringes. Qt's DirectWrite engine ignores the request, GDI and FreeType honour it.
FONT_ANTIALIAS = {
    "subpixel": None,
    "grayscale": QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferAntialias,
}

# YASB_FONT_HINTING: how hard glyphs are snapped to the pixel grid.
FONT_HINTING = {
    "default": QFont.HintingPreference.PreferDefaultHinting,
    "none": QFont.HintingPreference.PreferNoHinting,
    "vertical": QFont.HintingPreference.PreferVerticalHinting,
    "full": QFont.HintingPreference.PreferFullHinting,
}


def get_env_path():
    return os.path.join(DEFAULT_CONFIG_DIRECTORY, ".env")


def load_env():
    """
    Load environment variables from a env_file file specified in the YASB configuration.

    The file wins over the inherited environment: a reload starts the new process with the old
    one's environment, so without override a variable loaded once could never change again.
    """
    env_path = get_env_path()
    if os.path.isfile(env_path):
        if not load_dotenv(env_path, override=True):
            logging.warning("Failed to load environment variables from %s", env_path)
        else:
            logging.info("Loaded environment variables from %s", env_path)


def set_font_engine():
    """
    Set the font engine for the application based on the YASB_FONT_ENGINE environment variable.
    """
    valid_engines = {"native", "freetype", "gdi"}
    font_engine = os.getenv("YASB_FONT_ENGINE", "gdi").lower()
    if font_engine not in valid_engines:
        logging.warning("Unknown font engine '%s', falling back to 'gdi'", font_engine)
        font_engine = "gdi"
    os.environ["QT_QPA_PLATFORM"] = f"windows:fontengine={font_engine}"


def _env_choice(name: str, choices: Mapping[str, object], default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        logging.warning("Unknown %s '%s', falling back to '%s'", name, value, default)
        return default
    return value


def font_rendering_options() -> tuple[str, str]:
    """(antialias, hinting) from YASB_FONT_ANTIALIAS and YASB_FONT_HINTING, defaults 'subpixel' and 'default'."""
    return (
        _env_choice("YASB_FONT_ANTIALIAS", FONT_ANTIALIAS, "subpixel"),
        _env_choice("YASB_FONT_HINTING", FONT_HINTING, "default"),
    )


def apply_font_rendering(app: QApplication) -> None:
    """
    Put YASB_FONT_ANTIALIAS / YASB_FONT_HINTING on the application font.

    Stylesheet fonts only set family, size and weight, and inherit the rest from the application
    font, so every widget picks these up. With both unset the application font is left untouched.
    """
    antialias, hinting = font_rendering_options()
    if antialias == "subpixel" and hinting == "default":
        return
    font = QFont(app.font())
    strategy = FONT_ANTIALIAS[antialias]
    if strategy is not None:
        font.setStyleStrategy(strategy)
    font.setHintingPreference(FONT_HINTING[hinting])
    app.setFont(font)
    logging.info("Font rendering: antialias=%s, hinting=%s", antialias, hinting)
