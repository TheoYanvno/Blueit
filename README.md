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
2. ✅ Reddit search through the official API: app-only sign-in, a descriptive User-Agent, rate limits, retries, and a `fetch` command
3. ✅ Series joining: when `fetch` finds the final part of a finished series, it looks up the earlier parts in the author's own posts, puts them in order (part number, then date), checks each one, and saves the joined story with every part's link to `listings/<subreddit>.series.json`
4. ✅ Story library: every finished story `fetch` finds (and every joined series) is saved once, by its Reddit id, in a SQLite file (`library.db`). Fetching it again refreshes its score and text but never resets it, so narrated stories stay narrated. `find` searches it by subreddit, words and status, and `mark` marks a story narrated

5. ✅ Pick stories from menus: `python -m blueit ui` opens a page in your browser where drop-down menus choose the kind of story (scary, paranormal, revenge, work, family drama, funny), one subreddit or all of them, how recent, how long, the minimum upvotes and how many posts to look at. Results are added to the library, and the Library tab searches it and marks stories narrated

6. ✅ Narration with a stock voice: `narrate` reads a story aloud with a voice built into Windows (or eSpeak NG elsewhere), in short pieces joined with natural pauses, starting with the title and the author's name, and saves when every piece is spoken. Each story gets its own folder with the script and a credit file

7. ✅ Pictures: still images from `images/` (or from a story's own `output/<story>/images/`), each on screen for about `picture_seconds` and changing only between sentences, repeating in order or in a shuffle that stays the same for each story

8. ✅ Captions: every narrated sentence becomes short two-line captions timed to the voice, saved as a standard `captions.srt` file you can also upload to YouTube or TikTok

9. ✅ The video: FFmpeg shows the pictures in turn (filled to the frame and cropped, never stretched), plays the narration and burns in the captions, into `full.mp4` (upright 1080×1920 for phones by default, or widescreen), as H.264 and AAC that every site and phone plays

10. ✅ 1-minute parts: `full.mp4` is cut into `part-01.mp4`, `part-02.mp4`, … of at most `clip_seconds` each, only between sentences, with the captions kept, ready for Shorts, Reels and TikTok

Next: a voice cloned from your own recordings (later), and one `run` command for the whole thing.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp blueit.example.toml blueit.toml
python -m unittest
```

Needs Python 3.11+ and, for the video steps, [FFmpeg](https://ffmpeg.org/).

### Reddit access

Blueit reads posts through Reddit's official API, which needs a free app:

1. Sign in to Reddit and open <https://www.reddit.com/prefs/apps>.
2. Click **create another app**, choose **script**, and use `http://localhost:8080` as the redirect URI.
3. Copy `.env.example` to `.env` and paste in the id (under the app's name) and the secret. `.env` is ignored by git.

```
python -m blueit fetch                      # saves listings/<subreddit>.json and adds finished stories to library.db
python -m blueit check listings/nosleep.json
python -m blueit find                       # every story in the library, highest score first
python -m blueit find cabin -r nosleep      # stories from r/nosleep with "cabin" in the title or text
python -m blueit find --status new          # stories that haven't been narrated yet
python -m blueit mark 1abc23                # mark a story narrated (--new to undo)
```

### Pick stories from menus

```
python -m blueit ui                         # opens http://localhost:8642 in your browser
```

Choose **What kind of stories** (each kind is a short list of subreddits where people post whole stories, set in `blueit/categories.py`), then **Where** (all of them or one), **Posted in the**, **How long** (narration runs about 150 words a minute), **At least this many upvotes** and **Posts to look at**, and press **Find stories**. Finished stories go into the library; the **Library** tab lists them, searches them and marks them narrated. The page only answers on your own computer (localhost).

Blueit signs in with application-only access: it can read public posts and nothing else. It waits when Reddit's rate limit runs out and retries busy responses with growing waits.

### Narrate a story

```
python -m blueit narrate --next             # the highest-scored story that isn't narrated yet
python -m blueit narrate 1abc23             # one story by id
python -m blueit narrate --next --voice silent   # a quick preview with no sound
```

Each story gets a folder in `output/`: `script.txt` (exactly what's read aloud), `credit.txt` (the author and links), `narration.wav` and `narration.json` (when every sentence is spoken, for captions). Pick the voice in `blueit.toml`: `voice_engine = "windows"` uses the voices that come with Windows (set `voice = "Zira"` or `"David"`, and `voice_rate` from -10 to 10); `"espeak"` uses [eSpeak NG](https://github.com/espeak-ng/espeak-ng). The story text is passed to the voice through a file, never on a command line, so nothing in a post can run as a command.

### Make the video

```
python -m blueit video 1abc23               # captions.srt, full.mp4 and part-01.mp4, part-02.mp4, … for a narrated story
```

Put your pictures in `images/` first (or in the story's own `output/<story>/images/`). Needs [FFmpeg](https://ffmpeg.org/download.html) (on Windows: `winget install ffmpeg`). Settings in `blueit.toml`: `video_size`, `captions`, `picture_seconds`, `shuffle_pictures` and `clip_seconds`.

## Using other people's stories

Reddit posts belong to the people who wrote them, and Reddit's API terms apply to anything fetched through it. Blueit keeps each story's author and link with the video so you can credit them. Ask the author before posting a video of their story publicly; many story writers say yes when asked.

Built with help from AI coding tools; every part was reviewed and tested by me.
