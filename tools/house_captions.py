"""House captions: how every caption is drawn and checked.

Every number here was fitted to finished reference ads, so don't change them to suit one video.

  caption_img(text)       -> 1080x1920 RGBA: white text, black stroke, soft shadow, at most two lines
  balance_lines(text)     -> breaks a wide caption into two even lines, never top heavy
  check_spans(caps, cuts) -> hard checks: no blanks between captions, every cut on a caption change,
                             no caption over two lines or under 0.2s
"""
import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
# Metropolis Medium (public domain), the same file CapCut ships as its system font
FONT = os.environ.get("CAPTION_FONT") or os.path.join(HERE, "..", "fonts", "Metropolis-Medium.ttf")
CAP_SIZE = 69
FPS = 30
# A caption wider than this (measured in the font at size 100) goes on two lines. Every one-line caption a human
# editor kept measured 1184 or less; every one they broke measured 1234 or more. Width is measured, not counted,
# because digits and capitals are wide and a long line runs into the platform's buttons at the sides.
ONE_LINE_W = 1200


def text_w(s):
    return ImageFont.truetype(FONT, 100).getlength(s)


def balance_lines(text):
    """Wider than ONE_LINE_W: two lines as even as possible, never top heavy (a longer bottom line is better)."""
    if text_w(text) <= ONE_LINE_W or "\n" in text:
        return text
    w = text.split()
    best = min(range(1, len(w)), key=lambda i: (abs(text_w(" ".join(w[:i])) - text_w(" ".join(w[i:])))
                                              + (100 if text_w(" ".join(w[:i])) > text_w(" ".join(w[i:])) else 0)))
    return " ".join(w[:best]) + "\n" + " ".join(w[best:])


def wrap(text, f):
    if "\n" in text:                     # already broken into even lines
        return text.split("\n")
    meas = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if meas.textlength(t, font=f) > 885 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + [cur]


def outlined(lines, bases, size=CAP_SIZE, bold=False):
    """White text, black stroke, soft black drop shadow to the lower right."""
    S = 3
    f = ImageFont.truetype(FONT, size * S)

    def draw(stroke, fill_w):
        lay = Image.new("L", (1080 * S, 1920 * S), 0)
        d = ImageDraw.Draw(lay)
        for ln, b in zip(lines, bases):
            w = d.textlength(ln, font=f)
            d.text((540 * S - w / 2, b * S), ln, font=f, fill=255, anchor="ls", stroke_width=stroke, stroke_fill=255)
        return lay.resize((1080, 1920), Image.LANCZOS)
    edge = draw(11, 0).filter(ImageFilter.GaussianBlur(0.7))
    shadow = Image.new("L", (1080, 1920), 0)
    shadow.paste(edge, (4, 4))
    shadow = shadow.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.8))
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    black = Image.new("RGBA", (1080, 1920), (0, 0, 0, 255))
    im.paste(black, (0, 0), shadow)
    im.paste(black, (0, 0), edge)
    fill = draw(1 if bold else 0, 0).filter(ImageFilter.GaussianBlur(0.5))
    im.paste(Image.new("RGBA", (1080, 1920), (255, 255, 255, 255)), (0, 0), fill)
    return im


def caption_img(text):
    """Baselines at y 1465 for one line, 1430 and 1500 for two: inside the centred 4:5 safe zone."""
    f = ImageFont.truetype(FONT, CAP_SIZE)
    ls = wrap(text, f)
    return outlined(ls, [1465] if len(ls) == 1 else [1430, 1500])


def check_spans(caps, cut_frames, first=None, last=None, fatal=True):
    """caps: [(first frame, end frame, text)] in order. Fails loudly instead of letting a broken edit through."""
    errs = []
    for (a0, a1, at), (b0, b1, bt) in zip(caps, caps[1:]):
        if a1 != b0:
            errs.append("blank or overlap between %r (ends %d) and %r (starts %d)" % (at, a1, bt, b0))
    starts = {c[0] for c in caps}
    if last is not None:
        starts.add(last)
    for f in cut_frames:
        if (first is None or f >= first) and (last is None or f <= last) and f not in starts:
            errs.append("shot change at frame %d (%.2fs) is not on a caption change" % (f, f / FPS))
    f = ImageFont.truetype(FONT, CAP_SIZE)
    for a0, a1, t in caps:
        if len(wrap(t, f)) > 2:
            errs.append("caption over two lines: %r" % t)
        if a1 - a0 < 6:
            errs.append("caption under 0.2s: %r" % t)
    if errs and fatal:
        raise SystemExit("caption check failed:\n  " + "\n  ".join(errs))
    return errs
