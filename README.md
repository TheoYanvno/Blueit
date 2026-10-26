# Blueit

Blueit finds finished stories on Reddit, narrates them, and turns each one into a video of still pictures. Every video is saved whole and also split into 1-minute parts.

```
Reddit search ─▶ finished-story check ─▶ clean text ─▶ narration audio ─▶ video with your pictures
                                                                         └▶ output/<story>/full.mp4
                                                                            output/<story>/part-01.mp4, part-02.mp4, …
```

It starts with scary and creepy stories (r/nosleep, r/LetsNotMeet, r/Glitch_in_the_Matrix, r/TrueScaryStories, r/shortscarystories). Change the list in `blueit.toml`.

## What counts as a finished story

- It's a stand-alone story, or the last part of a series (titles like "(Final)", "(5/5)" or a "Series (Finished)" flair). For a final part, the earlier parts are found and joined in order.
- Its ending doesn't say more is coming ("to be continued", "update soon", "I'll post the next part").
- It hasn't been removed or deleted, it's between 400 and 12,000 words, and it isn't marked NSFW unless you allow it.

Run `python -m blueit check <saved listing.json>` to see which posts pass and why the others don't.

## Status

Built one piece a day. Done so far:

1. ✅ Finished-story check, text cleaning for narration, settings, `check` command and tests

Next: Reddit search through the official API, joining series parts, a story library that skips repeats, narration with a stock voice (a voice cloned from your own recordings comes later), pictures from your `images/` folder, the video with captions, 1-minute parts, and one `run` command for the whole thing.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp blueit.example.toml blueit.toml
python -m unittest
```

Needs Python 3.11+ and, for the video steps, [FFmpeg](https://ffmpeg.org/).

## Using other people's stories

Reddit posts belong to the people who wrote them, and Reddit's API terms apply to anything fetched through it. Blueit keeps each story's author and link with the video so you can credit them. Ask the author before posting a video of their story publicly; many story writers say yes when asked.

Built with help from AI coding tools; every part was reviewed and tested by me.
