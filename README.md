# ClipHunter Studio (V2)

A quality-first highlight studio for gaming streams. It watches YouTube/Twitch channels, or takes a video or link you
drop in. It finds moments, has an AI editor judge them against a strict 100-point rubric, re-checks every candidate
with an independent second AI pass, and only renders the clips that survive. **Zero clips is a valid result** for
ordinary footage.

## What changed from V1, and why the old clips were bad

| V1 problem | V2 fix |
|---|---|
| Moments picked by loudness/chat alone, and GTA is loud all the time | Multimodal signals: streamer voice-band intensity, quiet-then-loud contrast, sudden sounds, chat bursts, and a cheap keyframe scan for big screen changes, flashes and the grey "Wasted" screen. Signals only *nominate*; they never decide. |
| Fixed 30 s window around the peak | The AI picks **setup → key action → reaction → payoff → end** (10–60 s). Clutches keep their setup; quick reactions stay short. |
| AI judged blind (transcript failing, never saw the video) | Groq cloud transcription with word timestamps, plus **frames sent to vision models** (a frame grid and the key frame). If a model can't see, it's told so and can't score visuals. |
| Single lenient 6/10 check | 100-point rubric with written justifications, deterministic rejection rules, then an **independent second review** that can reject anything. ≥ 85 = top pick, 70–84 = review, < 70 = rejected. |
| Tried to fill a quota | Max 5 per video **as a limit**, near-duplicate removal, overlapping chunks so nothing is missed or counted twice |

## Install (Windows, once)

1. Install **Python** from python.org and tick **"Add Python to PATH"**.
2. Double-click **INSTALL.bat**. Restart once if it installed ffmpeg.
3. Double-click **START.bat**. The studio opens at http://127.0.0.1:7860

Updating from V1: copy these files over your old folder and choose Replace. Your settings, clips and `data`
folder are kept and upgraded automatically.

## Set up the AI (recommended: free Groq)

**Settings → AI & vision**:
- Provider **Groq**, paste a free key from console.groq.com/keys.
- Text model: `openai/gpt-oss-120b`. Vision model: `meta-models/muse-spark-open`, or any model Groq lists with
  image input.
- Press **Test connection & vision**. You want **Text ✓** and **Vision ✓**.
- **Transcription**: choose **Groq cloud**. It reuses the same key.

Meta Muse or Google Gemini keys work too. Muse/Gemini models can usually see images with no separate vision model.
Without AI, the app still finds moments, but they stay "unverified" and can never become top picks.

## Using it

- **Create clips**: drop a video anywhere on the window, or paste a YouTube/Twitch link. Pick the game (or Auto).
- **Projects**: real processing stages and progress, cancel/retry, a loudness timeline with every judged moment,
  and a table of **every moment and why it was kept or rejected**.
- **Highlights**: top picks, review queue, approved and rejected. Sort by quality, gameplay significance,
  entertainment, duration or timeline. Filter by game, highlight type or project. Hover a card to preview it.
- **Editor**: drag the clip start/end on the timeline (setup, action and payoff are marked). You can change the
  hook, title and caption (with 5 AI alternatives), fix transcript words, and pick a caption style (Bold, Clean,
  Neon, Minimal) and position. Choose an aspect ratio (9:16, 1:1, 16:9) and a layout (Facecam split, Blur fill,
  Center crop, Follow action), draw the webcam box, set volume, and turn dead-air cutting on or off. Then render,
  approve and export.
  Keys: `Space` play selection, `I`/`O` set start/end, `R` render, `J`/`K` previous/next, `A` approve, `X` reject,
  `?` all shortcuts.
- **Live channels**: add channels; streams are recorded and reviewed every few minutes while live.
- **Results**: log real views, % viewed, likes and shares, or import a CSV. After 6 results the AI is told what
  works for *your* channels, and rankings move by at most ±5 points per category.
- **Game profiles**: Open world/GTA, FPS, Battle royale, Sandbox, Horror, Sports/racing, Just chatting, General. Each
  one defines its highlight types, what to reject and which signals matter. Add your own in `core/profiles.py`.

Approved clips go to `APPROVED_CLIPS` with a `.txt` holding the title, caption, scores and clip ID.

## Tests

`python -m pip install pytest`, then `python -m pytest tests`. This covers 9 synthetic footage cases:
- ordinary gameplay
- loud-but-ordinary gameplay
- a high-skill clutch
- a loud reaction to nothing
- a silent visual fail (with and without vision)
- a long build-up
- duplicates
- a chunk-boundary event
- no webcam/chat

Plus no-AI safety, editor re-render, thresholds, API and unit tests. The V1 vs V2 comparison is written to
`tests/results/comparison.md`.

These tests use a rule-based stand-in AI, so they prove the pipeline does the right thing given sensible judgements.
How good a real model's taste is can only be judged on real streams.

## Honest limits

- Webcam detection needs `opencv-python` and finds faces that stay in one place. You can always draw the box by hand.
- Separate speakers aren't detected (one caption style for everyone).
- Views/likes percentages are AI guesses, not predictions you can bank on.
- Your PC must stay on while watching live channels. 720p recording uses about 2–3 GB of internet per hour.
- Only clip creators who allow it, and avoid story spoilers.
