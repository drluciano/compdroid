# Native runtime (M1+)

C++ / NDK library loaded by the Android app. Components, in build order:

1. **Loader** – maps exefs NSOs into a reserved region matching the Switch 39-bit layout; merges
   permissions where segments share a 16 KB page (`compdroid scan` reports where).
2. **Rewriter** – patches the sites `compdroid scan` finds: `svc #n` to a branch into a host
   trampoline, `mrs/msr TPIDR(RO)_EL0` to per-thread host values, `CNTPCT/CNTVCT/CNTFRQ` reads
   to values rescaled to 19.2 MHz.
3. **HLE kernel** – threads, sync, memory, handles, address arbitration.
4. **HLE services** – fs (romfs + saves), hid (SDL), audio renderer, time, settings, applet stubs.
5. **NVN → Vulkan** – hook `nvnBootstrapLoader`, hand the game our function table.
6. **Maxwell shader translator** → SPIR-V, with an on-disk pipeline cache.
7. **Presentation** – internal resolution, FSR 1 / SGSR, SMAA, frame generation, pacing.
8. **Overlay + driver loader** – Dear ImGui menu, libadrenotools for Turnip.

Starting point: the LASRecompAndroid engine (MIT), generalised so game-specific code moves to profiles.
