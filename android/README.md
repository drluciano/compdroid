# Android app shell (M1)

Gradle project for the template APK the builder fills in: start screen, driver picker (also on the
launcher icon's long-press menu), settings storage, and the native runtime library. The builder injects
the game's exefs and its profile under a per-game package name (`dev.compdroid.<titleid>`) and signs it
with a key generated locally. RomFS is pushed to the app's storage over adb rather than packed in the APK.
