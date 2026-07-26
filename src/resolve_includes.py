"""Bundle `-- #include <Name>` directives into a single self-contained file.

Global.lua (and any similarly-authored script) references sibling modules
with a bare-name directive, e.g. `-- #include Card`. This inlines the actual
contents of the referenced .lua file (resolved relative to the containing
script's own directory) in place of that directive, wrapped in matching
`-- #include <Name>.lua` marker comments so the inlined block's origin and
extent stay visible:

    -- #include Card.lua
    <contents of Card.lua>
    -- #include Card.lua

Resolution is recursive: if an included file (e.g. Card.lua) itself has
`#include` directives, those are inlined first, so nothing but plain Lua and
marker comments remains in the final output. The source files are never
touched -- everything is written to a new file.

With --watch, it re-bundles automatically whenever any source file in the
include graph (the input plus everything it transitively includes) changes,
so it stays running instead of exiting after one pass.

Usage:
    python src/resolve_includes.py
    python src/resolve_includes.py --input src/Global.lua --output src/Global.-1.lua
    python src/resolve_includes.py --watch
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "src" / "Global.lua"
DEFAULT_POLL_INTERVAL = 0.5

INCLUDE_RE = re.compile(r"^(?P<indent>\s*)--\s*#include\s+(?P<name>\S+)\s*$")


def default_output_for(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.-1{input_path.suffix}")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def read_text_preserving_newlines(path: Path) -> str:
    # newline="" disables universal-newline translation entirely, so
    # untouched lines keep their exact original line ending instead of being
    # silently rewritten to the platform default (e.g. bare \n turning into
    # \r\n on Windows). Path.read_text has no newline= param on this Python
    # version, hence plain open().
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def inline_includes(path: Path, stack: tuple[Path, ...], touched: set[Path]) -> str:
    """Return `path`'s content with every `#include` directive replaced by
    the referenced file's own fully-inlined content, wrapped in matching
    begin/end marker comments. `stack` is the chain of files currently being
    inlined (for circular-include detection); `touched` accumulates every
    source file visited, which --watch uses to know what to keep an eye on."""
    path = path.resolve()
    if path in stack:
        cycle = " -> ".join(p.name for p in (*stack, path))
        raise RecursionError(f"Circular #include detected: {cycle}")
    touched.add(path)

    lines = read_text_preserving_newlines(path).splitlines(keepends=True)
    base_dir = path.parent

    out = []
    for line in lines:
        stripped = line.rstrip("\r\n")
        match = INCLUDE_RE.match(stripped)
        if match is None:
            out.append(line)
            continue

        name = match.group("name")
        filename = name if name.endswith(".lua") else f"{name}.lua"
        newline = line[len(stripped):] or "\n"
        indent = match.group("indent")
        marker = f"{indent}-- #include {filename}{newline}"
        target = base_dir / filename

        if not target.exists():
            print(f"WARNING: {filename} not found next to {path.name}; leaving directive as-is")
            out.append(marker)
            continue

        inlined = inline_includes(target, (*stack, path), touched)
        if inlined and not inlined.endswith(("\n", "\r")):
            inlined += newline
        out.append(marker)
        out.append(inlined)
        out.append(marker)

    return "".join(out)


def resolve_all(input_path: Path, output_path: Path) -> set[Path]:
    """Bundle `input_path` into `output_path`. Returns every source file that
    took part in the bundle -- exactly what --watch needs to keep an eye on."""
    touched: set[Path] = set()
    bundled = inline_includes(input_path, (), touched)

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write(bundled)
    print(f"{now} :: Wrote {rel(output_path)}")
    return touched


def watch(input_path: Path, output_path: Path, poll_interval: float) -> None:
    watched = resolve_all(input_path, output_path)
    mtimes = {p: p.stat().st_mtime for p in watched}
    print(f"Watching {len(watched)} file(s) for changes (Ctrl+C to stop)...")

    try:
        while True:
            time.sleep(poll_interval)
            changed = False
            for p, prev_mtime in mtimes.items():
                try:
                    current_mtime = p.stat().st_mtime
                except FileNotFoundError:
                    changed = True
                    break
                if current_mtime != prev_mtime:
                    changed = True
                    break
            if not changed:
                continue

            watched = resolve_all(input_path, output_path)
            mtimes = {p: p.stat().st_mtime for p in watched}
    except KeyboardInterrupt:
        print("\nStopped watching.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--watch", action="store_true",
        help="Keep running, re-bundling whenever a file in the include graph changes",
    )
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args()

    output = args.output or default_output_for(args.input)
    if args.watch:
        watch(args.input, output, args.poll_interval)
    else:
        resolve_all(args.input, output)


if __name__ == "__main__":
    main()
