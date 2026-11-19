"""Checks this computer is ready: Python packages, ffmpeg and the caption font."""
import os
import sys

ok = True


def check(name, fn):
    global ok
    try:
        msg = fn()
        print("  ok    %s%s" % (name, (": " + msg) if msg else ""))
    except Exception as ex:  # noqa: BLE001
        ok = False
        print("  FAIL  %s: %s" % (name, ex))


print("Python %s" % sys.version.split()[0])
check("numpy, pillow", lambda: (__import__("numpy"), __import__("PIL"))[1].__version__)
check("ffmpeg", lambda: __import__("imageio_ffmpeg").get_ffmpeg_exe())
check("faster-whisper (transcripts)", lambda: __import__("faster_whisper").__version__)
check("torch + torchaudio (word alignment)",
      lambda: (lambda ta: hasattr(ta.functional, "forced_align") and ta.__version__ or (_ for _ in ()).throw(
          RuntimeError("this torchaudio has no forced_align: pip install 'torchaudio==2.8.*'")))(__import__("torchaudio")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def font():
    import house_captions as HT
    from PIL import ImageFont
    return " ".join(ImageFont.truetype(HT.FONT, 20).getname())


check("caption font", font)
print("Ready" if ok else "Not ready: fix the FAIL lines above (see README.md)")
sys.exit(0 if ok else 1)
