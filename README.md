# AI voiceover: cut and caption

A Claude Code skill for the two fiddliest parts of an AI voiceover ad:

1. **Cutting the voiceover.** Every breath, pause and bit of dead air goes, and every word still plays whole. The voice is only cut where it pauses for punctuation, so it never sounds clippy.
2. **Captioning it.** Short phrases in a clean house look: white text with a black outline and soft shadow, low in the 4:5 safe zone. Each caption changes on the exact frame its first word is spoken and holds until the next one, with no blanks.

The cut and caption timing are tuned against a human editor's hand-made cuts, to within a frame. Everything else (picture, B-roll, music) stays in your own workflow. You get back:

| File | What it is |
|---|---|
| `out/voiceover_cut.wav` | The cut voiceover, levelled to -16 LUFS. Edit your picture to this. |
| `out/captions.srt` | The captions as subtitles, for any editor |
| `out/timeline.json` | Every caption's and every word's time on the cut voiceover, for placing B-roll cuts on caption changes |
| `out/preview.mp4` | Captions over black with the cut voice, to check timing (`--preview`) |
| `out/captioned.mp4` | Your picture edit with the cut voice and burned-in captions (`--video your_edit.mp4`) |
| `out/captions_overlay.mov` | The captions alone on a transparent background, frame-accurate, to drop on top in any editor (`--overlay`) |

Works on **Mac and Windows**. It's been tested on a Mac. The Windows setup is included but hasn't been tested on a Windows computer yet.

## What you need

- **Claude Code**, in the Claude desktop app or the terminal.
- **Python 3.9 to 3.13.** Mac: from [python.org](https://www.python.org/downloads/). Windows: from [python.org](https://www.python.org/downloads/), with **"Add python.exe to PATH"** ticked during install.
- About 4 GB of free space, mostly for the speech models, which download the first time you use them.
- A voiceover as an MP3 or WAV, for example from ElevenLabs.

## Setup (once per computer)

Download this repo (the green **Code** button, then **Download ZIP**, or `git clone`). Put it somewhere that **isn't synced to iCloud or OneDrive**.

**Mac:** open Terminal in the repo folder and run:

```bash
bash setup/setup_mac.sh
```

**Windows:** open PowerShell in the repo folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
```

It finishes by running a check that should say **Ready**. Run the check again any time with `tools/doctor.py`.

## Using it

Open the repo folder in Claude Code and ask, for example:

> Cut and caption this voiceover: `ads/gift-ad/voiceover.mp3`. Hook A is the first line, then the body starts at "Here's how I did it".

Claude follows `.claude/skills/vo-cut-captions/SKILL.md`. It reads the words, writes the caption phrases, and builds the cut voice and a preview. Edit your picture to `voiceover_cut.wav`, then:

> Burn the captions into `ads/gift-ad/my_edit.mp4`.

### Running it yourself

```bash
.venv/bin/python tools/vo_captions.py words ads/gift-ad/job.json
.venv/bin/python tools/vo_captions.py build ads/gift-ad/job.json --preview
.venv/bin/python tools/vo_captions.py build ads/gift-ad/job.json --video ads/gift-ad/my_edit.mp4
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`. The job file format is at the top of `tools/vo_captions.py`, and `examples/job.json` is a template.

## What's in here

| Path | What it is |
|---|---|
| `.claude/skills/vo-cut-captions/SKILL.md` | The steps and rules Claude follows |
| `tools/vo_captions.py` | Cuts the voice, times the captions and writes the outputs |
| `tools/house_captions.py` | The caption look and its checks (no blanks, two lines at most, nothing under 0.2s) |
| `tools/transcribe.py` | Word-by-word transcript (faster-whisper, runs offline) |
| `tools/align_words.py` | Re-times every word against the audio itself (wav2vec2), which is what makes the timing frame-accurate |
| `tools/doctor.py` | Checks the setup |
| `fonts/` | Metropolis Medium, the caption font (public domain) |

## Good to know

- **Cut first, then edit the picture.** Captions and B-roll are timed to the cut voiceover, so cutting afterwards throws everything out of sync.
- If the AI voice garbles or adds a word, regenerate that line rather than captioning it.
- The caption checks fail the build rather than let a broken caption through. If one fails, split or join captions in the job file.
- Your voiceovers, transcripts and renders stay on your computer. `ads/`, `out/`, `tx/` and media files are kept out of git.
