"""Bake a main.py into an env-immune frozen opponent.

`bench.py` runs both agents in the same process, so a `KAG_*` env var set to
sweep *our* agent is also read by a `.py` opponent loaded from disk -- both
sides get the override and the comparison silently becomes a mirror match.
Freezing replaces `_tune` with a defaults-only version so the opponent keeps
the values it was committed with, whatever the environment says.

    python freeze.py <src.py> <out.py>
    git show HEAD:main.py > /tmp/prev.py && python freeze.py /tmp/prev.py /tmp/frozen.py
"""

import sys

LIVE = '''def _tune(name, default):
    raw = os.environ.get("KAG_" + name)
    return type(default)(raw) if raw is not None else default'''

FROZEN = '''def _tune(name, default):
    return default  # frozen by freeze.py -- ignores KAG_* overrides'''


def main():
    src, out = sys.argv[1], sys.argv[2]
    text = open(src).read()
    if LIVE not in text:
        sys.exit(f"{src}: _tune definition not found (did main.py change?)")
    open(out, "w").write(text.replace(LIVE, FROZEN, 1))
    print(f"froze {src} -> {out}")


main()
