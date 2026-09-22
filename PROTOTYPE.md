# Prototype v1

This branch builds a custom SameBoy libretro core for **Android ARM64**.

The prototype is deliberately narrow:

- It activates only when the ROM header title is `POKEPINBALL`.
- It reads Pokemon Pinball's `wCurrentStage` at `0xD4AC`.
- Red/Blue top and bottom field stages are cached into one 160x280 output.
- The vertical offset is 136 pixels (`0x88`), matching the game's own stage-transition math.
- Bonus stages are shown as a centered normal 160x144 screen.
- Other Game Boy / Game Boy Color games keep stock SameBoy behavior.

## Known prototype limitations

This is a first proof of concept, not the final full-board renderer.

The inactive half is a cached framebuffer, so moving sprites can remain stale until that half becomes active again. Pokemon Pinball also horizontally scrolls the field; v1 does not yet reconstruct the extra horizontal area. The next renderer should rebuild the board from tile/VRAM state rather than only caching the two normal Game Boy viewports.

The GitHub Actions workflow compiles an `arm64-v8a` compatible libretro `.so` intended for 64-bit RetroArch on Android.
