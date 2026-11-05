"""Pictures for the video: which still image is on screen when.

Pictures come from the story's own `images/` folder inside its output folder if it has one, or else
from the shared `images/` folder in blueit.toml. Each picture stays on screen for about
`seconds_each`, and changes only between sentences (at a caption boundary), so a picture never
switches in the middle of a line. With more time than pictures, they repeat in order; the order is
the file names' order, or a shuffle that's the same every time for the same story.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

PICTURE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


class PictureError(RuntimeError):
    pass


def find_pictures(story_folder: Path, shared: Path) -> list[Path]:
    """The pictures for one story: its own images/ folder if it has pictures, else the shared folder."""
    for folder in (Path(story_folder) / "images", Path(shared)):
        if folder.is_dir():
            found = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PICTURE_TYPES),
                           key=lambda p: p.name.lower())
            if found:
                return found
    raise PictureError(f"No pictures found. Put .jpg, .png or .webp files in {Path(shared)}/ "
                       f"(or in {Path(story_folder) / 'images'}/ for this story only).")


@dataclass(frozen=True)
class Shot:
    picture: Path
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return round(self.end - self.start, 3)


def plan(pictures: list[Path], segments, seconds_each: float = 8.0, shuffle_seed: str | None = None) -> list[Shot]:
    """Splits the narration's time into shots. `segments` are the narration's timed pieces (with
    .start and .end); a shot ends at the first piece boundary at least `seconds_each` after it began,
    and the last shot runs to the end of the narration."""
    if not pictures:
        raise PictureError("no pictures to show")
    if not segments:
        raise PictureError("the narration has no timings")
    if seconds_each <= 0:
        raise PictureError("seconds_each must be more than 0")
    order = list(pictures)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(order)
    total = segments[-1].end
    cuts = [0.0]
    for seg in segments[:-1]:
        # a boundary is the start of the next piece; cut there once the current shot is long enough
        boundary = seg.end
        if boundary - cuts[-1] >= seconds_each and total - boundary >= seconds_each / 2:
            cuts.append(boundary)
    cuts.append(total)
    return [Shot(order[i % len(order)], round(a, 3), round(b, 3)) for i, (a, b) in enumerate(zip(cuts, cuts[1:]))]
