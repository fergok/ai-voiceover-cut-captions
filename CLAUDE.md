# AI voiceover: cut and caption

When someone asks to cut, tighten or caption an AI voiceover, or to put captions on a voiceover video, use the `vo-cut-captions` skill in `.claude/skills/vo-cut-captions/` and follow it step by step.

- Run the tools with the repo's own Python: `.venv/bin/python` on Mac, `.venv\Scripts\python` on Windows. If `.venv` is missing, run the setup script for this computer first (README.md).
- Put each video in its own folder under `ads/` (it's kept out of git).
- Cut the voiceover before the picture is edited: the picture is timed to the cut voice.
- Save every correction the user makes as a rule in the skill, so it never needs making twice.
