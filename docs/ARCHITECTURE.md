# Architecture

Living plan: <https://claude.ai/artifact/P67xPNjyF7Q2DNuGd199Kt>. This file records the decisions.

## Decisions

- **Native execution only, no emulation, no recompilation step (2026-11-07).** Switch and Android
  phones are both AArch64, so the game's code runs directly. Static recompilation to C (the LAS Recomp
  approach) stays available as a later fallback only if a specific game needs it.
- **Base engine:** LAS Recomp (peiikai, MIT) and its Android port LASRecompAndroid (mamcjr), which
  BOTWRecompAndroid also builds on. Native-mode ideas follow d2r-mobile and MacNativeGames (no code
  taken unless the license allows).
- **Builder language:** Python 3.11+, no native dependencies, packaged later as a Windows .exe. This
  replaces the .NET idea in the first draft of the plan: it matches the reference projects' tooling,
  runs anywhere, and can be tested without Windows.
- **Per-game knowledge lives in `profiles/`,** never in the runtime.

## Pipeline

1. `inspect`: read `main.npdm` (title ID) and each NSO's build ID; match a profile.
2. `scan`: list the rewrite sites native mode needs (svc, TLS registers, counters) and 16 KB page issues.
3. `build` (M1): apply profile patches and the rewrite, inject into the template APK, zipalign, sign.
4. `deploy` (M1): adb install, push romfs into the app's storage.

## Reference ports surveyed

| Project | Approach | Graphics |
| --- | --- | --- |
| [LASRecomp](https://github.com/peiikai/LASRecomp) | static recomp, desktop | NVN → Vulkan / Metal |
| [LASRecompAndroid](https://github.com/mamcjr/LASRecompAndroid) | recomp on phone or native | NVN → Vulkan |
| [BOTWRecompAndroid](https://github.com/mamcjr/BOTWRecompAndroid) | recomp on phone or Native Mode | NVN → Vulkan |
| [SavageWindRecomp](https://github.com/Revivedx/SavageWindRecomp) | static recomp, desktop | NVN → Vulkan |
| [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) | native execution (incl. Android) | NVN → Vulkan / Metal |
| [totk-mobile](https://github.com/OJZen/totk-mobile) | native execution | NVN → Metal |
| [MacNativeGames](https://github.com/ly05010419/MacNativeGames) | one native runtime, 20+ games via per-game folders | NVN → Metal |

## Guardrails

- Input is an extracted `exefs/` + `romfs/` only. NSP, XCI, NCA and key files are refused.
- No game code, assets, shaders, keys or firmware in this repo. `.gitignore` blocks the usual names.
- Built APKs contain the user's game code and stay on the user's own devices.
