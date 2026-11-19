"""Word-level transcript of a voiceover, on Mac or Windows.

  transcribe.py <voiceover.mp3>      writes tx/<name>.json next to the audio

Uses faster-whisper (large-v3-turbo) on the CPU, so it needs no graphics card. The first run downloads the model
(about 1.6 GB). Whisper only supplies the words: align_words.py re-times every one against the audio.
Output: {"segments": [{"text", "start", "end", "words": [{"word", "start", "end"}]}]}
"""
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):        # Windows consoles default to an old code page
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")


def tx_path(audio):
    return os.path.join(os.path.dirname(os.path.abspath(audio)), "tx", os.path.splitext(os.path.basename(audio))[0] + ".json")


def transcribe(audio):
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=False, beam_size=5)
    out = []
    for s in segs:
        out.append(dict(text=s.text, start=round(s.start, 3), end=round(s.end, 3),
                        words=[dict(word=w.word, start=round(w.start, 3), end=round(w.end, 3)) for w in s.words]))
    return {"segments": out}


def main(audio):
    tx = transcribe(audio)
    out = tx_path(audio)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tx, f, indent=1, ensure_ascii=False)
    print("%d words -> %s" % (sum(len(s["words"]) for s in tx["segments"]), out))
    for s in tx["segments"]:
        print("  %6.2f  %s" % (s["start"], s["text"].strip()))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
