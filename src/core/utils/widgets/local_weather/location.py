"""Where the forecast is for: the laptop's position from Windows location, or the config address.

Coordinates stay in memory, rounded to two decimals (about 1 km), and are only ever logged at
DEBUG.
"""

from typing import Literal

# What a Windows location lookup hands back: a position, or why there is none ("off" when
# location is disabled or denied, "no_fix" when it is allowed but nothing came back in time).
LocateResult = tuple[float, float] | Literal["off", "no_fix"]
