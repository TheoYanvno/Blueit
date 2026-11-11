# Blueit

Blueit finds finished stories on Reddit, narrates them, and turns each one into a video of still pictures. Every video is saved whole and also split into 1-minute parts.

```
Reddit search ─▶ finished-story check ─▶ clean text ─▶ narration audio ─▶ video with your pictures
                                                                         └▶ output/<story>/full.mp4
                                                                            output/<story>/part-01.mp4, part-02.mp4, …
```

**Windows:** [download Blueit.exe](https://github.com/TheoYanvno/blueit/releases/latest/download/Blueit.exe) from the latest release, put it in its own folder and double-click it. It needs [FFmpeg](https://ffmpeg.org/download.html) (`winget install ffmpeg`). See [The Windows app](#the-windows-app).

It starts with scary and creepy stories (r/nosleep, r/LetsNotMeet, r/Glitch_in_the_Matrix, r/TrueScaryStories, r/shortscarystories). Change the list in `blueit.toml`.

## What counts as a finished story

- It's a stand-alone story, or the last part of a series (titles like "(Final)", "(5/5)" or a "Series (Finished)" flair). For a final part, the earlier parts are found and joined in order.
- Its ending doesn't say more is coming ("to be continued", "update soon", "I'll post the next part").
- It hasn't been removed or deleted, it's between 400 and 12,000 words, and it isn't marked NSFW unless you allow it.

Run `python -m blueit check <saved listing.json>` to see which posts pass and why the others don't.

## Quick start

```
python -m blueit doctor        # is everything set up?
python -m blueit ui            # pick stories from menus, then press Make video on one
python -m blueit run --fetch   # or do it all from the terminal
```

Each finished story ends up in `output/<story>/` as `full.mp4` plus `part-01.mp4`, `part-02.mp4`, …, with `captions.srt` and `credit.txt` next to them.

## How it was built

One piece at a time, each with its own tests:
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
11. ✅ One command for the whole thing: `run` checks FFmpeg, your pictures and the voice first, then (with `--fetch`) finds new stories, narrates the top waiting ones and makes their full videos and parts
12. ✅ Make videos from the page: every story in `blueit ui` has a **Make video** button that narrates it (if it isn't yet) and makes its full video and parts in the background, one story at a time, with the progress shown at the top of the page
13. ✅ `doctor`: checks Python, FFmpeg, the voice (it says a test line), your pictures, the Reddit keys, the library and the output folder, and says how to fix anything missing

14. ✅ Version 1.0: the whole path from Reddit to finished videos works from the terminal or the page, with 113 tests (including real FFmpeg runs)
15. ✅ A React page: Find stories, Library, a page for each story with Make video and a player, and Setup with the doctor checks and settings
16. ✅ Share to YouTube: connect your own Google project once, then upload the full video or any part from the story page, private by default, with the writer credited in the description
17. ✅ Post to TikTok: pick the full video or a part, download it, copy a ready caption that credits the writer, and open TikTok's upload page

Planned next: a narrator voice cloned from your own recordings, as another voice engine.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp blueit.example.toml blueit.toml
python -m blueit doctor      # checks everything below and says how to fix what's missing
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

Choose **What kind of stories** (each kind is a short list of subreddits where people post whole stories, set in `blueit/categories.py`), then **Where** (all of them or one), **Posted in the**, **How long** (narration runs about 150 words a minute), **At least this many upvotes** and **Posts to look at**, and press **Find stories**. Finished stories go into the library; the **Library** tab lists them, searches them and marks them narrated. Press **Make video** on any story to narrate it and make its videos without leaving the page; the progress shows at the top. The page only answers on your own computer (localhost).

The page has four parts:

- **Find stories**: the menus above, with the stories each search finds
- **Library**: every saved story, searchable by words, kind and status
- **Story**: open any story to read it, press **Make video**, then watch the full video or each part and download them
- **Setup**: the same checks as `blueit doctor`, with how to fix anything missing, and your current settings

The page is a React app in `ui/`, built into `blueit/static/` (already built in this repo). After changing it, run `npm install` and `npm run build` in `ui/`.

Blueit signs in with application-only access: it can read public posts and nothing else. It waits when Reddit's rate limit runs out and retries busy responses with growing waits.

### Narrate a story

```
python -m blueit narrate --next             # the highest-scored story that isn't narrated yet
python -m blueit narrate 1abc23             # one story by id
python -m blueit narrate --next --voice silent   # a quick preview with no sound
```

Each story gets a folder in `output/`: `script.txt` (exactly what's read aloud), `credit.txt` (the author and links), `narration.wav` and `narration.json` (when every sentence is spoken, for captions). Pick the voice in `blueit.toml`: `voice_engine = "windows"` uses the voices that come with Windows (set `voice = "Zira"` or `"David"`, and `voice_rate` from -10 to 10); `"espeak"` uses [eSpeak NG](https://github.com/espeak-ng/espeak-ng). The story text is passed to the voice through a file, never on a command line, so nothing in a post can run as a command.

### All at once

```
python -m blueit run --fetch                # find new stories, then narrate the top one and make its videos
python -m blueit run --count 3              # the top 3 waiting stories, one after another
```

### Make the video

```
python -m blueit video 1abc23               # captions.srt, full.mp4 and part-01.mp4, part-02.mp4, … for a narrated story
```

Put your pictures in `images/` first (or in the story's own `output/<story>/images/`). Needs [FFmpeg](https://ffmpeg.org/download.html) (on Windows: `winget install ffmpeg`). Settings in `blueit.toml`: `video_size`, `captions`, `picture_seconds`, `shuffle_pictures` and `clip_seconds`.

### Sharing to YouTube

Blueit uploads with the official YouTube Data API, using a Google Cloud project that you own (it's free for normal use):

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and turn on **YouTube Data API v3**.
2. Under **APIs & Services → OAuth consent screen**, set it up as **External** and add your own Google account as a test user.
3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app**, download the JSON, and save it as `youtube_client.json` in your Blueit folder.
4. In `blueit ui`, open a story with a made video and press **Connect YouTube**. Sign in and allow uploads. Blueit saves the sign-in as `youtube_token.json`.
5. Pick the full video or a part, choose who can see it (private, unlisted or public) and press **Upload to YouTube**. Upright parts get `#Shorts` in the title.

`youtube_client.json` and `youtube_token.json` are secrets: they're in `.gitignore`, stay on your computer, and are only sent to Google. Delete `youtube_token.json` to disconnect. While your Google project is in testing, Google may ask you to sign in again after a week. YouTube may also keep videos from new, unverified projects private until the project passes Google's audit.

### Posting to TikTok

TikTok's API only lets apps that have passed TikTok's audit post publicly; posts from apps that haven't are kept private. So Blueit prepares the post instead: on a story's page, pick the full video or a part, press **Download it**, **Copy caption** (the title, the part, the writer's credit and hashtags, within TikTok's 2,200 characters), then **Open TikTok upload**, choose the file and paste the caption.

### The Windows app

`Blueit.exe` is Blueit packaged with [PyInstaller](https://pyinstaller.org/), so Python isn't needed. Put it in a folder with your `blueit.toml`, `.env` and `images/`, then double-click it to open the page, or run `Blueit.exe doctor`, `Blueit.exe run --fetch` and the other commands in a terminal. FFmpeg still has to be installed (`winget install ffmpeg`).

Each version tag (like `v1.1.0`) builds it on GitHub Actions (`.github/workflows/windows-app.yml`) and attaches it to that release. To build it yourself on Windows:

```
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1    # makes dist\Blueit.exe
```

## Project layout

| File | What it does |
|---|---|
| `blueit/reddit.py` | Reddit's official API: app-only sign-in, rate limits and retries |
| `blueit/complete.py`, `series.py` | Is it a finished story? Joining the parts of a finished series |
| `blueit/clean.py` | Turns Reddit Markdown into text that reads well aloud |
| `blueit/library.py` | The SQLite story library |
| `blueit/categories.py`, `web.py` | The menus page and its small local server |
| `blueit/narrate.py` | Voices, pieces, pauses and timings |
| `blueit/pictures.py`, `captions.py` | Which picture shows when, and the caption lines |
| `blueit/video.py`, `parts.py` | FFmpeg: the full video and the 1-minute parts |
| `blueit/project.py`, `pipeline.py` | Each story's folder, script and credit, and the steps in order |
| `blueit/cli.py`, `doctor.py` | The commands, and the setup check |
| `blueit/youtube.py` | Signing in to YouTube and resumable uploads |
| `ui/` | The React page, built into `blueit/static/` |
| `packaging/` | The Windows app's entry point and build script |
| `tests/` | `python -m unittest` |

## Using other people's stories

Reddit posts belong to the people who wrote them, and Reddit's API terms apply to anything fetched through it. Blueit keeps each story's author and link with the video so you can credit them. Ask the author before posting a video of their story publicly; many story writers say yes when asked.

Built with help from AI coding tools; every part was reviewed and tested by me.

## License

MIT. See [LICENSE](LICENSE).
