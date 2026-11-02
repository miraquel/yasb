"""The traffic widget's sparkline: a tiny live bar graph of download and upload speed.

Qt-free; ``sparkline_view.TrafficSparkline`` paints the rectangles this hands it. Download bars
grow up from a 1px baseline and upload bars hang below it, on one log scale shared by both
directions, so a trickle next to a burst still shows. The newest sample is on the right.
"""

import math
from collections import deque
from dataclasses import dataclass

# x, y, width, height in whole pixels.
Rect = tuple[int, int, int, int]


def log_speed(bytes_per_sec: float) -> float:
    """The scale both directions share: 0 when idle, 1 at 9 KiB/s, about 4 at 10 MiB/s."""
    return math.log10(1 + max(0.0, bytes_per_sec) / 1024)


@dataclass(frozen=True)
class SparklineRects:
    baseline: Rect
    download: tuple[Rect, ...]
    upload: tuple[Rect, ...]


class SparklineModel:
    """The last ``bars`` (download, upload) samples in bytes/s, and the bars they draw as."""

    def __init__(
        self,
        bars: int = 12,
        bar_width: int = 2,
        bar_gap: int = 1,
        height: int = 16,
        scale_floor: int = 65536,
        download_threshold: float = 0,
        upload_threshold: float = 0,
    ):
        self.bars = bars
        self.bar_width = bar_width
        self.bar_gap = bar_gap
        self.height = height
        self.scale_floor = scale_floor
        self.download_threshold = download_threshold
        self.upload_threshold = upload_threshold
        self.width = bars * (bar_width + bar_gap) + 2
        # Upload gets the smaller share of the height below the baseline row.
        self.up_max = round(0.4 * (height - 1))
        self.down_max = height - 1 - self.up_max
        self._samples: deque[tuple[float, float]] = deque([(0.0, 0.0)] * bars, maxlen=bars)

    @property
    def samples(self) -> list[tuple[float, float]]:
        """Oldest first."""
        return list(self._samples)

    def push(self, download: float, upload: float) -> None:
        """Add a sample on the right; the oldest one drops off the left."""
        self._samples.append((float(download), float(upload)))

    def peak(self) -> float:
        """Full scale: the busiest sample in the window, but never below ``scale_floor``."""
        return max([log_speed(self.scale_floor), *(log_speed(v) for sample in self._samples for v in sample)])

    @staticmethod
    def _bar_height(value: float, threshold: float, max_height: int, peak: float) -> int:
        # Idle (below the label's threshold) draws nothing; anything above it at least 1px.
        if value <= 0 or value < threshold:
            return 0
        return min(max_height, max(1, round(log_speed(value) / peak * max_height)))

    def heights(self) -> list[tuple[int, int]]:
        """(download, upload) bar heights in pixels, oldest first."""
        peak = self.peak()
        return [
            (
                self._bar_height(down, self.download_threshold, self.down_max, peak),
                self._bar_height(up, self.upload_threshold, self.up_max, peak),
            )
            for down, up in self._samples
        ]

    def bar_x(self, index: int) -> int:
        return 1 + index * (self.bar_width + self.bar_gap)

    def rects(self) -> SparklineRects:
        download: list[Rect] = []
        upload: list[Rect] = []
        for i, (down, up) in enumerate(self.heights()):
            x = self.bar_x(i)
            if down:
                download.append((x, self.down_max - down, self.bar_width, down))
            if up:
                upload.append((x, self.down_max + 1, self.bar_width, up))
        return SparklineRects(
            baseline=(0, self.down_max, self.width, 1),
            download=tuple(download),
            upload=tuple(upload),
        )
