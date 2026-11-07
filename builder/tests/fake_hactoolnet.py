"""Stand-in for hactoolnet in tests: no crypto, it just mimics the CLI surface CompDroid uses."""
import json
import os
import sys
from pathlib import Path

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
from fixtures import make_npdm, make_nso, words  # noqa: E402

args = sys.argv[1:]
log = os.environ.get("FAKE_HAC_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(args) + "\n")


def opt(name):
    return args[args.index(name) + 1] if name in args else None


kind = opt("-t")
if not opt("-k") or not os.path.isfile(opt("-k")):
    print("keys missing", file=sys.stderr)
    sys.exit(1)
if kind == "xci":
    out = Path(opt("--securedir"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "aaaa.program.nca").write_bytes(b"P" * 64)
    (out / "bbbb.control.nca").write_bytes(b"C" * 16)
    sys.exit(0)
if kind == "nca":
    target = args[args.index("nca") + 1]
    if "--exefsdir" not in args:
        print("NCA:\n  Content Type:                 " + ("Program" if "program" in target else "Control"))
        sys.exit(0)
    exefs = Path(opt("--exefsdir"))
    romfs = Path(opt("--romfsdir"))
    exefs.mkdir(parents=True)
    romfs.mkdir(parents=True)
    (exefs / "main.npdm").write_bytes(make_npdm())
    (exefs / "main").write_bytes(make_nso(words(0xD4000001)))
    (romfs / "patched.txt" if "--basenca" in args else romfs / "base.txt").write_text("x")
    sys.exit(0)
sys.exit(2)
