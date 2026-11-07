# tools/

Put third-party helper programs here. Nothing in this folder is committed.

- **hactoolnet.exe** (required for .nsp / .xci): downloaded here automatically from
  <https://github.com/Thealexbarney/LibHac/releases> the first time you open a package. If that
  fails (no internet), download the Windows build yourself and copy `hactoolnet.exe` here.
  CompDroid runs it with your own `prod.keys` to read your game package.
- **nsz** (only for .nsz / .xcz): `py -m pip install nsz`. No file needed here.

Firmware is not needed.
