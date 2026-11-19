---
name: vo-cut-captions
description: Cut an AI voiceover (ElevenLabs or any TTS file) to the sound, with every breath and pause gone and every word whole, then time and burn house-style captions on the exact frame each phrase is spoken. Use whenever the user asks to edit, cut, tighten or caption an AI voiceover, to add captions to a voiceover video, or makes any video ad with an AI voice, even if they only say "put captions on this" or "cut the VO".
---

# AI voiceover: cut and caption

This skill does two jobs, the same way every time:
1. **Cuts the voiceover.** Every breath, every pause and all the dead air go. Every word plays whole, and the voice is only cut where it pauses for punctuation.
2. **Captions it.** Short phrases in the house look. Each one changes on the exact frame its first word starts and holds until the next one, with no blanks.

Everything else in the video (picture, B-roll, music, review) is the user's own workflow. Do the cut first, because the picture is timed to the cut voiceover. Cutting breaths afterwards throws the whole timeline out of sync.

The tool is `tools/vo_captions.py` in this repo. Run it with the repo's Python: `.venv/bin/python` on Mac, `.venv\Scripts\python` on Windows (`PY` below). If `.venv` is missing, run the setup script first (README.md).

## Steps

1. **Set up a folder for the video** under `ads/<name>/` with the voiceover in it. If the user has the script, keep it to hand. The voiceover is what gets captioned, so the script only helps you spot words the AI voice changed.
2. **Read the words.** `PY tools/vo_captions.py words ads/<name>/job.json` (write a job file with only `"vo"` first). The first run transcribes and aligns the voiceover, which downloads the speech models once. It prints every word with its time. Check the transcript against the script: a word the AI voice garbled or added is a line to regenerate, not one to caption.
3. **Write the job file** (`examples/job.json` is a template):
   - `vo`: the voiceover file.
   - `ranges` (optional): the parts of the voiceover to keep, in order, as `[start, end]` in its seconds. Use this when one file holds several hooks: `[[0, 5.8], [17.4, 60.2]]` is hook A plus the body. Leave it out to keep the whole file.
   - `cuts` (optional): spans to take out, such as a fluffed line.
   - `captions_from` (optional): no captions before this second. Use it when the hook has its own text box instead of captions.
   - `captions`: the caption phrases in order. Read in order, they must be exactly the words spoken. Follow the caption rules below.
4. **Build.** `PY tools/vo_captions.py build ads/<name>/job.json --preview`
   - It writes `out/voiceover_cut.wav`, `out/captions.srt`, `out/timeline.json` and `out/preview.mp4` (captions over black with the cut voice).
   - Read every `WARN` line and fix the job. A caption that "doesn't match the transcript" means its wording differs from what is said.
   - The build stops on a caption that breaks the house checks: a blank between captions, a caption over two lines, or one under 0.2s. Split or join captions to fix it.
5. **Hand the cut voice to the picture edit.** The user's own workflow builds the picture to `voiceover_cut.wav`. `timeline.json` has every caption's start and end and every word's time on the new timeline. B-roll changes on the same frame as a caption change, so use the caption starts as the cut points.
6. **Burn the captions.** `PY tools/vo_captions.py build ads/<name>/job.json --video <their edit.mp4>`
   - This writes `out/captioned.mp4`: their picture with the cut voiceover and the captions. Add `--video-audio 0.5` to keep their music or sound effects under the voice.
   - It warns about any picture cut that doesn't land on a caption change. Scene detection can mistake a light switching on for a cut, so look at each one.
   - If they edit in another app, `--overlay` gives `captions_overlay.mov`: the captions alone on a transparent background, frame-accurate, to lay over their timeline. `captions.srt` works too, but it loses the house look.
7. **Check before handing off.** Transcribe the cut voice (`PY tools/transcribe.py out/voiceover_cut.wav`) and compare it with the captions: every word is there once, with no ghost or doubled words. Look at a few frames of the video for caption placement. Say anything you couldn't check by ear.

## Caption rules

- **Lowercase, with no punctuation at line ends** except a question mark on a question. Keep names as written and capitalise "I". The tool strips trailing commas and full stops, but write captions without them anyway.
- **Captions match the spoken words exactly.** Numbers and units in house form: digits with units ("45 lbs", "100+"), $ on dollar amounts, and hyphenated compound modifiers ("2-in-1", "90-day money-back guarantee"). Brand and product names always appear in their exact form.
- **Short phrases, split where the voice pauses:** at commas and spoken pauses, so viewers can't read ahead of the voice. Find the pause in the audio (the `words` times), not the grammar. The voice may pause after a small word, and the split follows it.
- **Split at the sentence's natural break and leave them wanting the rest.** For example "this year I didn't want to", then "break the bank": the viewer asks "didn't want to what?". Never put a whole sentence in one caption. Don't chop so fine that a caption flashes past either ("this year" alone): join it to the next words.
- **List items get one caption each,** one at a time: "camping", then "fishing".
- **Two lines at most.** The tool breaks a wide caption into two even lines by its width on screen, never top heavy. If two lines still won't hold it, split it into two captions. Keep words that belong together on one line ("90-day guarantee"), or split the caption instead.
- **No emoji in captions,** except a deliberate one for a joke. No word highlight.
- The look and position are fixed: white Metropolis with a black stroke and soft shadow, centred low inside the 4:5 safe zone (y 1430 to 1500 at 1080x1920). Don't restyle it per video.

## What the voice cut does (so you can explain it)

- **No breath, ever.** A breath is a dip after a word, then about 0.2s of unvoiced hiss running into the next word. It is cut from the dip to the next word's onset, and each one is printed (`breaths cut:`). A word's own fading "s" and a stop's release ("dark.") are not breaths, and they're kept.
- **Cut to the sound, not the transcript.** A word ends about 0.03s after its sound drops below about -45 dB and starts right where its sound begins. A soft opening ("f", "th", "h") is followed back into the quiet. A one-word list item runs until its fade reaches silence. Silent dips of 0.04s or more between words go.
- **Only cut at punctuation.** A cut inside a phrase ("60 / day / guarantee") sounds clippy, so it's undone unless there's a real pause of 0.25s or more (`joined N voice cuts`).
- **No added pauses.** The output keeps whole words and no extra air. If an ad needs a beat, the job can ask for one with `"pause": {"stop": 0.1, "comma": 0.07}`.
- **Every piece starts on a whole frame,** and a caption that opens a piece starts on that same frame, so the voice, the caption and the cut line up exactly.
- The video ends when the voice stops, so the voice track is the length of the video.

If the user says something sounds wrong ("that word's clipped", "there's still a gap after X"), find the time in `timeline.json` and look at the pieces around it. Fix it with `ranges` or `cuts` in the job, not by editing the audio by hand. If the same problem keeps coming back, it's a rule: add it here so it never needs saying twice.
