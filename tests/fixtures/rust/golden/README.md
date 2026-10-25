# Golden images

Rendered on the Windows host `nanoha-lan` (i9-12900K, RTX 3090, MSVC 19.44)
by the x64 Release app built at `298c041` with `tools/windows/build.ps1`.
The lane `tools/oracle/frame_dump.ps1` ran through `tools/windows/runtask.ps1`
in the console session (D3D9 needs it), with the fixture models staged next to
the exe (`tools/windows/stage.ps1`). It runs

    MikuDanceStudio.exe --mds-frame-dump tests\fixtures\rust\swing600-golden.pmm <out-dir> 0 150 300 599

Four runs gave the same bytes for every image.

| File | Frame | sha256 |
|---|---|---|
| `swing600-golden-0.png` | 0 | `715221b8ce6093ee9f6d547469e9101414d24332a2eff78b392af24f358aa9af` |
| `swing600-golden-150.png` | 150 | `aa5c7436ed97221244a2efde23d610e4eddd41f20d4d2ee4ef96f9d36bd419ee` |
| `swing600-golden-300.png` | 300 | `29328518412f564b5bd5d238e9dadcef27c7580dc30c406bb89aeb85a21760b4` |
| `swing600-golden-599.png` | 599 | `bdbf2f746ca592051d7eda9f8da463da9300e38a0079a57b3338368771f6a4a6` |

## Scene

`../swing600-golden.pmm` is `swing600.pmm` changed for rendering, built by
`tools/fixtures/gen_fixtures.py`. The models blend normally instead of
additively, the single camera key is turned half a turn (yaw = pi) so the
camera faces the fronts of the strips, the root bones of slots 1, 2, and 3
stand at x = -8, +8, and +12, and slot 0 has no outside-parent link. Physics
is on (mode 2). With the camera turned, x is mirrored on screen: slots 3 and 2
are on the left, slot 0 is in the middle, and slot 1 (`morph4.pmx`) is on the
right.

## Rendering

- `--mds-frame-dump` steps the same frame-step passes as `--mds-trace`, so an
  image of frame f shows the pose of frame f.
- The render is the picture-file output of the app: the scene is drawn into a
  recording window at a fixed 640x360 (the app's default output size, whatever
  the PMM says), without the text, line, sprite, or debug overlays.
- The back buffer was A8R8G8B8 with 8x multisampling, and the PNGs are 8-bit
  RGBA. Their alpha comes from the back buffer, as the app's picture output
  writes it.
- The projection is orthographic (camera perspective flag 1 in this PMM).
- No `Data\` folder was staged next to the exe, so the app ran with its
  built-in defaults instead of `Data\mmconfig.ini` and `Data\color.txt`. The
  background is white and the ground grid shows its axis lines.

## Contact rule

A golden frame is valid only where no two models touch. The models stand in
the same plane, so where two of them meet, the pixels depend on depth ties and
draw order. In a sweep of frames 0 to 600 in steps of 10, slots 2 and 3 touch
at frame 30, where physics swings their upper segments. Every other frame
sampled is clear, and so are the four frames above. Before you add a golden
frame, render it and check that no two models touch in it.
