# tools/

Put third-party helper programs here. Nothing in this folder is committed.

- **hactoolnet.exe** (needed only for .nsp / .xci): copy a hactoolnet you already have here.
  CompDroid runs it with your own `prod.keys` to read your game package. It is not downloaded
  for you: LibHac was removed from GitHub by a Nintendo DMCA notice in May 2025. Without it,
  open an extracted `exefs` + `romfs` folder instead.
- **nsz** (only for .nsz / .xcz): `py -m pip install nsz`. No file needed here.

Firmware is not needed.
