#!/usr/bin/env python3
"""Cut an AI voiceover to the sound and time house captions to it.

  vo_captions.py words <job.json>                      transcribe + align the voiceover, print every word's time
  vo_captions.py build <job.json> [options]            cut the voiceover, time the captions, write the outputs

build options:
  --out DIR            where to write (default: <job folder>/out)
  --video FILE         your finished picture edit, cut to the new voiceover: burns the captions into it -> captioned.mp4
  --video-audio VOL    also keep the video's own sound (music, sound effects) at this volume, e.g. 0.5 (default: off)
  --preview            captions over a black background with the cut voiceover -> preview.mp4
  --overlay            the captions alone on a transparent background -> captions_overlay.mov, for any editor

The job file (paths are relative to it):
  {
    "vo": "voiceover.mp3",
    "ranges": [[0, 5.76], [17.4, 60.2]],     optional: which parts of the voiceover to keep, in order (default: all)
    "cuts": [[31.2, 33.0]],                   optional: spans to take out, e.g. a line the AI voice fluffed
    "captions_from": 5.76,                    optional: no captions before this second of the original voiceover
    "captions": ["here's how I did it", "my gifts are always", "the safe ones"]
  }
Captions are short phrases that, read in order, are the words spoken. Each one shows from the frame its first word
starts until the next one starts. A caption can also be {"t": <original second>, "text": "..."}.

Outputs: voiceover_cut.wav (-16 LUFS), captions.srt, timeline.json (voice pieces, caption frames and every word's
time on the new timeline, for placing B-roll), plus whichever videos were asked for.
"""
import difflib
import json
import math
import os
import re
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import house_captions as HT  # noqa: E402

for _s in (sys.stdout, sys.stderr):        # Windows consoles default to an old code page
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FF = os.environ.get("FFMPEG") or imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1080, 1920, 30
ALIGN_LEAD = 0.03       # a caption goes up 0.03s before its word's aligned start


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("command failed: %s\n%s" % (" ".join(cmd[:6]), r.stderr[-1500:]))
    return r


def duration(path):
    err = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        sys.exit("can't read " + path)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


# ---------------------------------------------------------------- transcript and word timings

def load_job(path):
    e = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))
    e["vo"] = os.path.join(base, os.path.expanduser(e["vo"]))
    if e.get("vo_tx"):
        e["vo_tx"] = os.path.join(base, os.path.expanduser(e["vo_tx"]))
    if not os.path.exists(e["vo"]):
        sys.exit("voiceover not found: " + e["vo"])
    if not e.get("ranges"):
        e["ranges"] = [[0.0, duration(e["vo"])]]
    e["_base"] = base
    return e


def tx_of(e):
    import transcribe
    txp = e.get("vo_tx") or transcribe.tx_path(e["vo"])
    if not os.path.exists(txp):
        print("transcribing %s (the first run downloads the speech model)..." % os.path.basename(e["vo"]))
        transcribe.main(e["vo"])
    return txp


def aligned_words(e):
    """Whisper's words with forced-alignment times (align_words.py), made once and cached beside the transcript.
    Whisper's own word times are 100-300ms off at many boundaries; the aligned starts land within a frame."""
    if "_aw" not in e:
        txp = tx_of(e)
        out = re.sub(r"\.json$", "", txp) + ".aligned.json"
        if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(txp):
            import align_words
            print("aligning words to the audio (the first run downloads the alignment model)...")
            align_words.align(e["vo"], txp, out)
        e["_aw"] = json.load(open(out, encoding="utf-8"))["words"]
    return e["_aw"]


def vo_envelope(vo, hop=0.01):
    """10ms loudness of the voiceover in dB."""
    raw = subprocess.run([FF, "-v", "error", "-i", vo, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = int(16000 * hop)
    x = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((x ** 2).mean(1)) + 1e-9)


def vo_features(path):
    """Per 10 ms: level (dB), voicing (autocorrelation peak at 70-400 Hz pitch) and share of energy above 2 kHz.
    A breath is unvoiced hiss (voicing under ~0.35, mostly above 2 kHz); speech vowels are voiced (0.6-0.8)."""
    cache = os.path.join(os.path.dirname(path), "tx", os.path.splitext(os.path.basename(path))[0] + ".feat.npy")
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(path):
        return np.load(cache)
    raw = subprocess.run([FF, "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    sr, hop, win = 16000, 160, 480
    nf = max(0, (len(x) - win) // hop)
    fr = np.fft.rfftfreq(win, 1 / sr)
    hann = np.hanning(win)
    out = np.zeros((3, nf), np.float32)
    lo, hi = int(sr / 400), int(sr / 70)
    for f in range(nf):
        seg = x[f * hop:f * hop + win]
        out[0, f] = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)
        s2 = seg - seg.mean()
        ac = np.correlate(s2, s2, "full")[win - 1:]
        out[1, f] = ac[lo:hi].max() / ac[0] if ac[0] > 0 else 0
        sp = np.abs(np.fft.rfft(s2 * hann)) ** 2
        out[2, f] = sp[fr > 2000].sum() / (sp.sum() + 1e-12)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    np.save(cache, out)
    return out


# ---------------------------------------------------------------- cutting the voice

def keep(rng, removals):
    """rng minus removals, as a list of (a, b)."""
    a0, b0 = rng
    out, cur = [], a0
    for a, b in sorted(removals):
        if b <= cur or a >= b0:
            continue
        if a > cur:
            out.append((cur, min(a, b0)))
        cur = max(cur, b)
    if cur < b0:
        out.append((cur, b0))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 0.02]


def frame_of(t):
    return int(t * FPS + 1e-6)          # round down: a caption is never late


def run_in(db, on, floor=-45):
    """First frame of a word's rising onset: walk back from the frame where it gets loud while the level keeps
    rising and stays above `floor` (the "s" of "so", the "a" of "and")."""
    f = on
    while f > 0 and db[f - 1] > floor and db[f - 1] < db[f]:
        f -= 1
    return f


def sound_pieces(e, rngs, floor=-45, onset_floor=-50, rel=28, lead=0.02, tail=0.03, min_gap=0.04, look=0.3, short=0.6):
    """Voice pieces cut to the sound itself, the way a human editor cuts by hand: a word ends about 0.03s after its
    sound falls below about -45 dB, starts right where its sound begins, and any silent dip between two words goes,
    even 0.04s. Aligned word timings only find each word: its audible span is read from the level, against the
    word's own peak, so faint breath or room tone around it is not kept and a soft opening is not clipped.
    Every word plays whole: a soft opening ("fff" in "free") is followed back to where the sound leaves silence,
    and a short piece (a one-word list item) runs until its fade reaches silence. Words within `min_gap` stay joined."""
    words = aligned_words(e)
    env = vo_envelope(e["vo"])
    n = len(env)
    quiet_db = float(np.percentile(env, 5))
    onset_floor = max(-66.0, min(onset_floor, quiet_db + 8))
    tail_floor = max(-66.0, min(floor, quiet_db + 8))

    def span(w, prev_end, next_start):
        """A word's audible span. Start: walk back from the loud part while the level stays above `floor`, keeping
        at most 0.15s quieter than the word's peak - `rel` (a soft "f", "th" or "h" is kept, a long breath is not).
        End: walk on while above `floor`, through a stop's closure of up to 0.05s to its release ("dark.",
        "stock,"), never into the next word."""
        a, b = int(round(w["start"] * 100)), int(round(w["end"] * 100))
        a, b = max(0, min(a, n - 1)), max(0, min(max(b, a + 1), n))
        peak = max(env[a:b]) if b > a else env[a]
        loud = max(floor, peak - rel)
        lo = max(0, int(round((prev_end + 0.02) * 100)), a - int(look * 100))
        hi = min(n, int(round((next_start - 0.03) * 100)), b + int(look * 100))
        i = a
        if env[i] > loud:
            while i > lo and env[i - 1] > loud:
                i -= 1
        else:
            i = next((k for k in range(a, b) if env[k] > loud), a)
        quiet = 0
        while i > lo and env[i - 1] > onset_floor:
            if env[i - 1] <= loud:
                quiet += 1
                if quiet > 15:
                    break
            i -= 1
        j = b
        while j < hi:
            if env[j] > floor:
                j += 1
                continue
            k = next((k for k in range(j + 1, min(hi, j + 6)) if env[k] > floor), None)
            if k is None:
                break
            j = k
        while j > i + 1 and env[j - 1] <= floor:     # the aligned end can sit after the sound has stopped
            j -= 1
        k = j                                         # the fade after the word, down to silence (0.12s at most)
        while k < min(hi, j + 12) and env[k] > tail_floor and env[k] <= env[k - 1] + 3:
            k += 1
        return i / 100, j / 100, k / 100

    out = []
    for r0, r1 in rngs:
        ws = [w for w in words if r0 - 0.05 <= w["start"] < r1]
        if not ws:
            continue
        idx = {id(w): k for k, w in enumerate(words)}
        sp = []
        for w in ws:
            k = idx[id(w)]
            pe = words[k - 1]["end"] if k else -1.0
            ns = words[k + 1]["start"] if k + 1 < len(words) else 1e9
            sp.append(span(w, pe, ns))
        for k in range(1, len(sp)):          # keep spans in order, never overlapping
            sp[k] = (max(sp[k][0], sp[k - 1][0]), max(sp[k][1], sp[k - 1][0]), max(sp[k][2], sp[k - 1][0]))

        def close(c):
            end = c[2] if c[1] - c[0] < short else c[1]
            out.append((max(0.0, c[0] - lead), end + tail))
        cur = list(sp[0])
        for a, b, full in sp[1:]:
            if a - cur[1] >= min_gap:
                close(cur)
                cur = [a, b, full]
            else:
                cur[1], cur[2] = max(cur[1], b), max(cur[2], full)
        close(cur)
    for x in range(1, len(out)):             # padding never overlaps the next piece
        if out[x][0] < out[x - 1][1]:
            mid = (out[x - 1][1] - tail + out[x][0] + lead) / 2
            out[x - 1] = (out[x - 1][0], mid)
            out[x] = (mid, out[x][1])
    return out


def cut_breaths(e, pieces, rngs, tail_db=-42, hump_db=-46, rise=4, min_hump=0.15, voiced=0.35, onset=-30, link=0.06):
    """No inhale or exhale at a pause, ever. A breath is its own burst of sound: the word fades, the level dips, then
    rises again for 0.2s or so of unvoiced hiss that runs straight into the next word. Cut from the dip to the next
    word's rising onset. NOT a breath: a word's own fading tail ("face.", "case.": the "s" runs on and falls into
    silence) and a stop's release ("dark.": a short burst after a short dip, then silence). Never cut by voicing alone."""
    words = aligned_words(e)
    F = vo_features(e["vo"])
    db, vo = F[0], F[1]
    n = len(db)

    def onset_of(w, lo):
        z0 = max(lo, int((w["start"] - 0.25) * 100))
        return next((f for f in range(z0, min(n, int(w["end"] * 100) + 5))
                     if db[f] > onset or (vo[f] >= 0.5 and db[f] > -40)), None)

    cuts, found = [], []
    for r0, r1 in rngs:
        ws = [w for w in words if r0 - 0.05 <= w["start"] < r1]
        for k in range(len(ws) - 1):
            w, nw = ws[k], ws[k + 1]
            if nw["start"] - w["end"] < 0.12:
                continue
            a = int((w["end"] - 0.03) * 100)
            on = onset_of(nw, a + 1)
            if on is None:
                continue
            ri = run_in(db, on)
            t = next((f for f in range(a, ri) if db[f] < tail_db), None)       # the word has faded
            if t is None:
                continue
            dip = min(range(t, min(ri, t + 9)), key=lambda f: db[f])
            thr = max(db[dip] + rise, hump_db)
            hs = next((f for f in range(dip + 1, ri) if db[f] > thr), None)    # the hump after the dip
            if hs is None:
                continue
            he, f = hs, hs
            while f < ri:
                if db[f] > thr or (f + 1 < ri and db[f + 1] > thr):
                    he = f
                    f += 1
                else:
                    break
            length = (he - hs + 1) / 100
            if length < min_hump or vo[hs:he + 1].mean() >= voiced or (ri - he - 1) / 100 > link:
                continue
            # mid-phrase, after a word ending in a stop, a short silent closure and then hiss is the next word's own
            # "s", "f" or "sh", not a breath ("makes it | so much"). A breath sits at a pause: after punctuation,
            # or after at least 0.08s of quiet.
            if w["word"].strip()[-1:] not in ",.!?;:" and (hs - t) / 100 < 0.08:
                print("  kept (a consonant, not a breath): %s|%s %.2f-%.2f" % (w["word"], nw["word"], dip / 100, ri / 100 - 0.01))
                continue
            cuts.append((dip / 100, ri / 100 - 0.01))
            found.append("%s|%s %.2f-%.2f" % (w["word"], nw["word"], dip / 100, ri / 100 - 0.01))
        if ws:     # the first word of a range: no breath before it
            on = onset_of(ws[0], max(0, int((r0 - 0.3) * 100)))
            if on is not None:
                cuts.append((max(0.0, r0 - 0.05), run_in(db, on) / 100 - 0.02))
    if found:
        print("  breaths cut: " + "; ".join(found))
    out = [p for r in pieces for p in keep(r, cuts)]
    return [p for p in out if p[1] - p[0] >= 0.05]


def voice_pieces(e):
    """The parts of the original voiceover that play, in order: every word whole, no breath, no dead air."""
    rngs = [tuple(r) for r in e["ranges"]]
    cuts = [tuple(c) for c in e.get("cuts", [])]
    aw = aligned_words(e)
    pieces = [p for p in sound_pieces(e, rngs) for p in keep(p, cuts)]
    pieces = cut_breaths(e, pieces, rngs)
    if not e.get("phrase_cuts"):
        # The voice is only cut where it pauses for punctuation: cutting between "60" and "day" and "guarantee"
        # sounds clippy. A cut whose last word has no comma or full stop is undone, unless a real pause
        # (0.25s or more of removed air) sits there.
        merged, undone = [], 0
        for p in pieces:
            if merged:
                q = merged[-1]
                before = [w for w in aw if (w["start"] + w["end"]) / 2 < q[1]]
                same = any(r[0] - 0.4 <= q[0] and p[1] <= r[1] + 1.2 for r in rngs)
                cut_here = any(q[1] - 0.02 <= c[0] and c[1] <= p[0] + 0.02 for c in cuts)
                if (before and before[-1]["word"].strip()[-1:] not in ".,?!;:" and same and not cut_here
                        and p[0] - q[1] < 0.25):
                    merged[-1] = (q[0], p[1])
                    undone += 1
                    continue
            merged.append(tuple(p))
        if undone:
            print("  joined %d voice cuts that fell inside a phrase" % undone)
        pieces = merged
    # No pause is added back at a cut by default: the human editor's own cuts kept whole words and no extra air.
    # A job can ask for a beat with "pause": {"stop": 0.1, "comma": 0.07}.
    beat = dict(dict(stop=0.0, comma=0.0), **e.get("pause", {}))
    out = [tuple(pieces[0])] if pieces else []
    for p in pieces[1:]:
        q = out[-1]
        g = p[0] - q[1]
        same = any(r[0] - 0.4 <= q[0] and p[1] <= r[1] + 1.2 for r in rngs)
        cut_here = any(q[1] - 0.02 <= c[0] and c[1] <= p[0] + 0.02 for c in cuts)
        if g > 0 and same and not cut_here and max(beat.values()) > 0:
            before = [w for w in aw if (w["start"] + w["end"]) / 2 < q[1]]
            last = before[-1]["word"].strip()[-1:] if before else ""
            k = min(g, beat["stop"] if last in ".?!" else beat["comma"])
            if k >= g - 1e-6:
                out[-1] = (q[0], p[1])
                continue
            out[-1] = (q[0], q[1] + k * 0.6)
            p = (p[0] - k * 0.4, p[1])
        out.append(tuple(p))
    pieces = out
    # a range edge in the tail of a word leaves a sliver that plays as a click or half a breath: drop pieces under
    # 0.15s, unless one holds a whole spoken word ("the" in "with the free case" is a 0.06s burst)
    mids = [(w["start"] + w["end"]) / 2 for w in aw]
    short_words = [p for p in pieces if p[1] - p[0] < 0.15 and any(p[0] - 0.03 <= m <= p[1] + 0.03 for m in mids)]
    for p in short_words:
        print("  kept a short word: %.2f-%.2f" % p)
    return [p for p in pieces if p[1] - p[0] >= 0.15 or p in short_words]


# ---------------------------------------------------------------- captions

def norm(s):
    return re.sub(r"[^a-z0-9%$']", "", s.lower().replace("’", "'"))


def caption_words(e, aw):
    """Each caption with the aligned word it starts on."""
    caps = e.get("captions") or []
    if caps and all(isinstance(c, dict) and "t" in c for c in caps):
        return [(dict(c), min(aw, key=lambda w: abs(w["w_start"] - c["t"]))) for c in caps]
    # plain phrases: line them up with the transcript, word by word
    rngs = e["ranges"]
    pool = [w for w in aw if any(r0 - 0.05 <= w["start"] < r1 for r0, r1 in rngs)]
    pool.sort(key=lambda w: next(k for k, (r0, r1) in enumerate(rngs) if r0 - 0.05 <= w["start"] < r1))
    toks, owner = [], []
    for ci, c in enumerate(caps):
        text = c["text"] if isinstance(c, dict) else c
        for t in text.split():
            if norm(t):
                toks.append(norm(t))
                owner.append(ci)
    sm = difflib.SequenceMatcher(None, toks, [norm(w["word"]) for w in pool], autojunk=False)
    hit = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            hit[a + k] = b + k
    out, missing = [], []
    for ci, c in enumerate(caps):
        text = c["text"] if isinstance(c, dict) else c
        mine = [k for k, o in enumerate(owner) if o == ci]
        first = next((k for k in mine if k in hit), None)
        if first is None:
            missing.append(text)
            continue
        wi = hit[first] - (first - mine[0])          # back up over any unmatched leading words
        out.append((dict(text=text), pool[max(0, wi)]))
    if missing:
        print("WARN captions not found in the voiceover (check the wording against `words`):\n  " + "\n  ".join(missing))
    unmatched = len(toks) - len(hit)
    if unmatched:
        print("WARN %d caption words don't match the transcript word for word: check them" % unmatched)
    return out


def compile_timeline(e):
    pieces = voice_pieces(e)
    aw = aligned_words(e)

    # lay the pieces end to end, each starting on a whole frame, so caption, shot and voice piece share one tick
    vo, t = [], 0.0
    for i, (a, b) in enumerate(pieces):
        nxt_a = pieces[i + 1][0] if i + 1 < len(pieces) else 1e9
        # editors snap a piece's start to the next whole frame on save, shaving the word: start on the nearest one
        a0 = round(a * FPS) / FPS
        if not vo or a0 >= vo[-1]["src_out"] - 1e-6 or a < vo[-1]["src_in"]:
            a = a0
        up = a + max(1, math.ceil((b - a) * FPS - 1e-6)) / FPS     # round up: a whole frame never cuts a word tail
        b = up if up <= nxt_a + 1e-6 else a + max(1, math.floor((nxt_a - a) * FPS + 1e-6)) / FPS   # ...nor replays the next piece
        vo.append(dict(src_in=a, src_out=b, start=t))
        t += b - a
    total_speech = t

    def omap(ts):
        """original VO second -> output second (inside a removed span: the next kept piece)."""
        for p in vo:
            if p["src_in"] - 1e-6 <= ts <= p["src_out"] + 1e-6:
                return p["start"] + ts - p["src_in"]
            if ts < p["src_in"]:
                return p["start"]
        return total_speech

    total = total_speech + e.get("tail", 0.0)     # the video ends when the voice stops
    total_f = int(round(total * FPS))

    # Every caption starts on the frame its first word starts (aligned start less 0.03s). A caption that opens a
    # voice piece starts on the piece's own tick, so caption, cut and voice line up exactly.
    piece_f = [int(round(p["start"] * FPS)) for p in vo]
    frm = e.get("captions_from")
    events, prev = [], -1
    for c, w in caption_words(e, aw):
        if frm is not None and w["start"] < frm - 0.05:
            continue
        f = frame_of(omap(w["start"] - ALIGN_LEAD))
        near = [pf for pf in piece_f if f - 4 <= pf <= f + 12]
        if near:
            f = min(near, key=lambda pf: abs(pf - f))
        f = max(f, prev + 6)                       # never shorter than 0.2s
        events.append(dict(c, f=f))
        prev = f
    events.sort(key=lambda c: c["f"])
    if not events:
        sys.exit("no captions to place: add them to the job file (run `words` to see the transcript)")
    caps = []
    for i, c in enumerate(events):
        if c["f"] >= total_f:
            break
        end_f = events[i + 1]["f"] if i + 1 < len(events) else total_f   # hold until the next one: no blanks
        # no punctuation at line ends except "?"
        txt = "\n".join(re.sub(r"[,.;:!]+$", "", ln.rstrip()) for ln in c["text"].split("\n"))
        caps.append(dict(text=txt, f0=c["f"], f1=end_f, start=c["f"] / FPS, end=end_f / FPS))
    ticks = set(piece_f)
    off = [(c["text"], c["f0"], pf) for c in caps if c["f0"] not in ticks
           for pf in piece_f if -4 <= pf - c["f0"] <= 12][:20]
    if off:
        sys.exit("caption not on its voice piece's tick:\n  " +
                 "\n  ".join("%r at %.2fs, piece starts %.2fs" % (t, a / FPS, p / FPS) for t, a, p in off))
    HT.check_spans([(c["f0"], c["f1"], c["text"]) for c in caps], [], first=events[0]["f"], last=total_f)
    words = [dict(word=w["word"], start=round(omap(w["start"]), 3), end=round(omap(w["end"]), 3)) for w in aw
             if any(p["src_in"] - 0.02 <= w["start"] < p["src_out"] for p in vo)]
    return dict(vo=vo, captions=caps, words=words, total=total_f / FPS, fps=FPS)


# ---------------------------------------------------------------- outputs

def write_audio(e, tl, out):
    parts = []
    for j, p in enumerate(tl["vo"]):
        parts.append("[0:a]atrim=%.3f:%.3f,asetpts=PTS-STARTPTS,afade=t=in:d=0.008,afade=t=out:st=%.3f:d=0.008,adelay=%d:all=1[v%d]"
                     % (p["src_in"], p["src_out"], p["src_out"] - p["src_in"] - 0.008, p["start"] * 1000, j))
    labels = "".join("[v%d]" % j for j in range(len(tl["vo"])))
    parts.append("%samix=inputs=%d:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[vo]" % (labels, len(tl["vo"])))
    parts.append("[vo]amix=inputs=1:normalize=0:duration=longest,asetpts=N/SR/TB,atrim=0:%.3f,alimiter=limit=0.82[a]" % tl["total"])
    run([FF, "-v", "error", "-y", "-i", e["vo"], "-filter_complex", ";".join(parts), "-map", "[a]", "-ar", "48000", out])


def srt_time(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def write_srt(tl, out):
    with open(out, "w", encoding="utf-8") as f:
        for k, c in enumerate(tl["captions"], 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (k, srt_time(c["start"]), srt_time(c["end"]), HT.balance_lines(c["text"])))


def caption_frames(tl, work):
    """(first frame, end frame, png) for every caption."""
    os.makedirs(work, exist_ok=True)
    sched = []
    for k, c in enumerate(tl["captions"]):
        pth = os.path.join(work, "cap%03d.png" % k)
        HT.caption_img(HT.balance_lines(c["text"])).save(pth, compress_level=1)
        sched.append((c["f0"], c["f1"], pth))
    blank = os.path.join(work, "blank.png")
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    return sched, blank


def feed_frames(pr, tl, sched, blank):
    cache = {}
    data = lambda pth: cache.setdefault(pth, open(pth, "rb").read())
    pos, total_f = 0, int(round(tl["total"] * FPS)) + 1
    for f0, f1, pth in sorted(sched):
        for _ in range(pos, f0):
            pr.stdin.write(data(blank))
        for _ in range(max(pos, f0), f1):
            pr.stdin.write(data(pth))
        pos = max(pos, f1)
    for _ in range(pos, total_f):
        pr.stdin.write(data(blank))
    pr.stdin.close()
    if pr.wait():
        sys.exit("caption pass failed")


def shot_changes(video, total):
    """Frames where the picture cuts, so a cut that isn't on a caption change can be flagged."""
    r = subprocess.run([FF, "-v", "info", "-i", video, "-t", "%.3f" % total, "-vf",
                        "fps=%d,scale=160:-2,select='gt(scene,0.3)',showinfo" % FPS, "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [int(round(float(m) * FPS)) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def write_video(tl, audio, out, work, video=None, video_audio=0.0):
    """Captions over `video` (scaled to fill 1080x1920, 30fps, held on its last frame if short) or over black."""
    sched, blank = caption_frames(tl, os.path.join(work, "text"))
    if video:
        src = ["-i", video]
        base = ("[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d,setpts=N/(%d*TB),"
                "tpad=stop_mode=clone:stop_duration=600[b]" % (W, H, W, H, FPS, FPS))
    else:
        src = ["-f", "lavfi", "-i", "color=black:s=%dx%d:r=%d" % (W, H, FPS)]
        base = "[0:v]setpts=N/(%d*TB)[b]" % FPS
    amap = "1:a"
    filt = base + ";[2:v]format=rgba,setpts=N/(%d*TB)[t];[b][t]overlay=0:0:format=auto,format=yuv420p[v]" % FPS
    if video and video_audio > 0:
        filt += (";[0:a]volume=%.3f,apad[va];[1:a][va]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.82[a]"
                 % video_audio)
        amap = "[a]"
    pr = subprocess.Popen([FF, "-y", "-v", "error"] + src + ["-i", audio, "-f", "image2pipe", "-framerate", str(FPS),
                          "-c:v", "png", "-i", "-", "-filter_complex", filt, "-map", "[v]", "-map", amap,
                          "-c:v", "libx264", "-preset", "medium", "-b:v", "12M", "-maxrate", "14M", "-bufsize", "24M",
                          "-r", str(FPS), "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                          "-movflags", "+faststart", "-t", "%.3f" % tl["total"], out], stdin=subprocess.PIPE)
    feed_frames(pr, tl, sched, blank)


def write_overlay(tl, out, work):
    sched, blank = caption_frames(tl, os.path.join(work, "text"))
    pr = subprocess.Popen([FF, "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
                           "-c:v", "qtrle", "-pix_fmt", "argb", "-t", "%.3f" % tl["total"], out], stdin=subprocess.PIPE)
    feed_frames(pr, tl, sched, blank)


def cmd_words(job):
    e = load_job(job)
    aw = aligned_words(e)
    print("%d words. Original seconds (aligned start), as said:" % len(aw))
    line = []
    for w in aw:
        line.append("%.2f %s" % (w["start"], w["word"]))
        if w["word"].rstrip("\"')").endswith((".", "!", "?")) or len(line) >= 12:
            print("  " + " | ".join(line))
            line = []
    if line:
        print("  " + " | ".join(line))


def cmd_build(job, args):
    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    e = load_job(job)
    out = os.path.abspath(opt("--out", os.path.join(e["_base"], "out")))
    os.makedirs(out, exist_ok=True)
    video = opt("--video")
    if video and not os.path.exists(video):
        sys.exit("video not found: " + video)
    orig = sum(b - a for a, b in e["ranges"])
    tl = compile_timeline(e)
    audio = os.path.join(out, "voiceover_cut.wav")
    write_audio(e, tl, audio)
    write_srt(tl, os.path.join(out, "captions.srt"))
    json.dump(dict(tl, voiceover=e["vo"]), open(os.path.join(out, "timeline.json"), "w", encoding="utf-8"), indent=1)
    print("voice: %.2fs kept of %.2fs, %d pieces; %d captions" % (tl["total"], orig, len(tl["vo"]), len(tl["captions"])))
    for c in tl["captions"]:
        print("  %6.2f-%6.2f  %s" % (c["start"], c["end"], c["text"].replace("\n", " / ")))
    print("wrote %s, captions.srt, timeline.json" % audio)
    work = os.path.join(out, ".work")
    if video:
        vlen = duration(video)
        if abs(vlen - tl["total"]) > 0.2:
            print("WARN the video is %.2fs and the cut voiceover %.2fs: cut the picture to voiceover_cut.wav first" % (vlen, tl["total"]))
        dst = os.path.join(out, "captioned.mp4")
        write_video(tl, audio, dst, work, video, float(opt("--video-audio", 0)))
        caps = [(c["f0"], c["f1"], c["text"]) for c in tl["captions"]]
        bad = [m for m in HT.check_spans(caps, shot_changes(dst, tl["total"]), first=caps[0][0],
                                          last=int(round(tl["total"] * FPS)), fatal=False) if m.startswith("shot change")]
        if bad:
            print("WARN B-roll should change on the same frame as a caption (scene detection, so check each):\n  " + "\n  ".join(bad))
        print("wrote " + dst)
    if "--preview" in args:
        dst = os.path.join(out, "preview.mp4")
        write_video(tl, audio, dst, work)
        print("wrote " + dst)
    if "--overlay" in args:
        dst = os.path.join(out, "captions_overlay.mov")
        write_overlay(tl, dst, work)
        print("wrote " + dst)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("words", "build"):
        sys.exit(__doc__)
    if sys.argv[1] == "words":
        cmd_words(sys.argv[2])
    else:
        cmd_build(sys.argv[2], sys.argv[3:])
