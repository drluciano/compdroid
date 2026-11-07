# Profile format

One folder per title ID, one TOML file per game. The builder matches a dump by
`game.title_id` and by the leading hex digits of the `main` module's build ID.

Profiles hold **facts and our own patch logic only**: title IDs, build IDs,
offsets and short replacement byte strings. Never game code, assets, shaders,
keys or firmware.

```toml
[game]
title_id = "0100000000000000"   # 16 hex digits, from main.npdm
name = "Game name"
notes = "free text"

[[versions]]
version = "1.0.0"
main_build_id = "0123456789ABCDEF"  # prefix of `compdroid inspect` build ID; empty = not yet known
status = "untested"                 # untested | boots | ingame | playable | broken

[[versions.patches]]
id = "fps60"
description = "Unlock 60 fps"
module = "main"                     # exefs module name
offset = 0x123456                   # offset into decompressed .text
bytes = "1F 20 03 D5"               # replacement bytes (hex)
setting = "target_fps"              # optional: in-game setting that toggles it
```
