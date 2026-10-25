# mmegold: MME effects rendered by the C++ application

Golden images of the C++ application's MME path (the embedded MMEffect,
`third_party/mmeffect`), so that `mds-mmert` can compare pixels, and per image
a probe of the values each effect holds, so that it can compare the inputs
first.

Rendered on the Windows host `nanoha-lan` (i9-12900K, RTX 3090, driver
32.0.16.1062, VS 2022 Build Tools, x64 Release) by the app built at `8f3bed1`
with `tools/windows/build.ps1`. The back buffer was 3072x1728, A8R8G8B8
(format 21), 8x multisampling. `tools/oracle/mmegold.ps1` ran every scene twice
in the console session (`tools/windows/runtask.ps1`), and the two runs gave
the same bytes for every file. On the same build, `tools/oracle/golden2.ps1`
and `tools/oracle/frame_dump.ps1` gave the hashes of `../golden2/README.md`
and `../golden/README.md`.

## Regenerating

The inputs (the scene PMMs, the EMM templates, `control.fx`, and `anime.fx`)
come from `gen_mmegold.py`, which takes the PMM writer of
`../golden2/gen_golden2.py`:

    python3 -I tests/fixtures/rust/mmegold/gen_mmegold.py --write   # or --check

The outputs come from the Windows host, from a checkout at `<checkout>`, with
the ray-mmd corpus of `tools/fixtures/fetch_corpus.sh` (commit `218a91c`) at
`C:\mds\corpus\ray-mmd` (or pass `-Corpus`):

1. `tools\windows\build.ps1 -Root <checkout> -Testing OFF -Targets MikuDanceStudio`
2. `tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\mmegold.ps1
   -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir>'`

`mmegold.ps1` copies `chain8.pmx`, `morph4.pmx`, and the corpus's `ray.x` next
to the exe, and stages each PMM in `<Out>\stage` with its EMM. MMEffect takes
EMM effect paths as they are, so the lane writes the EMM with `$(fixtures)`,
`$(mmegold)`, and `$(corpus)` replaced by `<Out>\stage\effects` (a copy of
`../mme/effects`), `<Out>\stage\mmegold` (the two effects here and
`rust/crates/mds-mmert/tests/data/blink.gif`), and `<Out>\stage\ray-mmd` (a
copy of the corpus without `.git`). It runs `--mds-mme-dump` on each scene into
`<Out>\run1` and `<Out>\run2`, prints the size and sha256 of each file, and
exits 1 when a run fails, a probe lists no effect, a `TIME` parameter is not
the frame time, or the two runs differ. Copy `<Out>\run1\*` here. The frames
of each scene are listed in `mmegold.ps1` and in `SCENES` of `gen_mmegold.py`
(`gen_mmegold.py --frames` prints them). The MME log of each run goes to the
lane log (stderr of the app).

## The dump mode

`--mds-mme-dump <pmm> <out-dir> <frame>...` (`src/tools/trace_mode.cpp`) is
`--mds-frame-dump` through the app's own MME path. The PMM load notifies
MMEffect, whose first frame autoloads `<pmm stem>.emm` beside the PMM and
assigns the effects as the EMM load of the MME dialog does. The images are
the picture-file output, 640x360, as `../golden/README.md` describes. The
differences from `--mds-frame-dump`:

- Every pass from frame 0 is rendered, as AVI recording renders every frame,
  so `ELAPSEDTIME`, animated textures, and render targets see the frames the
  app would.
- Frame 0 is rendered once more before the passes. MMEffect takes the first
  non-edit frame's `ELAPSEDTIME` from the wall clock when the frame before it
  was in edit mode, and the app draws one while it loads. With that render
  `ELAPSEDTIME` is 0 at frame 0 and 1/30 after it.
- Playback is armed as for `--mds-trace` (`UpdateBoneFrames`), which disables
  the current-frame edit, so MMEffect runs in its non-edit mode: `TIME` is the
  timeline time (frame / 30), not the wall clock.

## The probe

`<scene>-<frame>.mme.txt`, written after the image of the frame; the format is
in `src/tools/trace_mode.cpp`. One `object` line per object MMEffect
registered (file, assigned effect, script class, render class, shown), then
per loaded effect, sorted by path, an `effect` line and one `param` line per
top-level bool, int, and float parameter: name, semantic (`-` for none), class
and type (`D3DXPARAMETER_CLASS`, `D3DXPARAMETER_TYPE`), rows x columns x
elements, and the values. Matrices are row by row. Floats are `%.9g`, which
reads back to the same float. Paths are relative to the PMM directory and may
hold spaces, so read the last six fields of an `effect` line from the right.

The values are what each effect holds after the frame. A per-object parameter
holds the value of the last draw that set it (the last material, and the edge
pass after the object pass), and a parameter no draw set holds its initial
value. An effect that the planner loads for an offscreen target
(`ray-mmd/materials/...`, `ray-mmd/shadow/...`) is listed as its own `effect`.

## Scenes

`chain8.pmx` stands at the origin in every scene, seen by a perspective camera
at (0, 4, 20) looking at (0, 4, 0) with a 30 degree view angle (yaw pi, so +x
is on the left of the image), which is the view of the frame hashes in
`rust/crates/mds-mmert/tests/frame_hash.rs`. Physics mode 0, no self-shadow,
light (-0.5, -1, 0.5).

| Scene | Frames | Effects (EMM rows) | What it checks |
|---|---|---|---|
| `objects` | 0, 30 | `Pmd0 = mme/effects/objects.fx` | An object effect: techniques by pass, subset and Use* filters, a looped technique script. |
| `post` | 0, 30 | `Pmd0 = mme/effects/post.fx` | A postprocess scene effect on a model: render targets, clears, `ScriptExternal`. The image is the post chain's output. |
| `offscreen` | 0, 30 | `Pmd0 = mme/effects/offscreen.fx` | `OFFSCREENRENDERTARGET` with `DefaultEffect` rows, `CONTROLOBJECT` of an absent model and of `(self)`. |
| `timeofday` | 0, 30 | `Pmd0 = ray-mmd/Skybox/Time of day/Time of day.fx` | The ray-mmd sky effect on a model: `TIME`, `ELAPSEDTIME`, many transform semantics. |
| `main` | 0, 30 | `Pmd0 = ray-mmd/Main/main.fx` | The ray-mmd material effect alone, as in `frame_hash.rs`. |
| `control` | 0, 15, 30 | `Pmd0 = mmegold/control.fx` | `CONTROLOBJECT` of a second model, `morph4.pmx` at x = 4 to 6, its morph あ from 0 to 1: a morph, a bone position and matrix, the model's position, world, visibility, and scale, and a missing model. The owner's color is (あ, frac(センター.x / 4), visible). |
| `anime` | 0, 3, 4, 9, 30 | `Pmd0 = mmegold/anime.fx` | `ANIMATEDTEXTURE` on `blink.gif` (4x2, delays 10, 0, and 20 cs, looping twice; `anime.rs` of mds-mmert), sampled by the model's UVs. |
| `ray` | 0, 30 | `Pmd0 = ray-mmd/Main/main.fx`, `Acs0 = ray-mmd/ray.fx` | ray-mmd as it is meant to run: `ray.fx` on the `ray.x` accessory, with its offscreen targets (MaterialMap, PSSM1-4 shadow maps, SSAO, lights, fog) and its post chain. |

## Notes for mmert

- Every PMM sets the draw order of its models 1-based, as the app writes it,
  and the camera mode flag. `../golden2/` writes draw order 0, which is the
  "camera/light/accessory" entry of the model combo; `ExpGetCurrentObject`
  reports such a model as no object when no accessory is loaded, and MMEffect
  then never applies the model's effect. With 1-based order and the model
  selected the app is in model mode and does not play the camera keys, hence
  the camera mode flag.
- `MOUSEPOSITION` (in `main`, `timeofday`, and `ray`) depends on the host's
  cursor and window positions. The two runs agreed, but another host or
  session will see other values; take them from the probe.
- `offscreen-*.png` and `timeofday-*.png` are the same image: the owner draws
  nothing visible. `main` shows the owner white.
- `ray-*.png` is black with broken grid lines, and frames 0 and 30 are the
  same image. Whether the C++ path or the scene (no sky, no `ray_controller.pmx`)
  causes that is not known; compare the probe before the pixels. The run logs
  `Warning: unsupported script command: ClearSetStencil=ClearStencil
  (technique: DeferredLighting)`.
- `anime-0` and `anime-3` are the same image, and so are `anime-9` and
  `anime-30`.

## Files

| File | sha256 |
|---|---|
| `anime-0.mme.txt` | `d55f9cd3fb221028f2929f09e4dfb72e5608e044f0fff44b603314a55bdc8468` |
| `anime-0.png` | `ac37c722054af720363b1a75c7ee04459fc74642f1ac257424376e62086b6887` |
| `anime-3.mme.txt` | `dc459984fc9840e842f57e0f2ed974f2adb3c2dadc8fe6d23c84ed15aac52ffb` |
| `anime-3.png` | `ac37c722054af720363b1a75c7ee04459fc74642f1ac257424376e62086b6887` |
| `anime-30.mme.txt` | `fa592fd562048371abdf5be48096daf49c6aa79f0a6c122ce693603c83c8f348` |
| `anime-30.png` | `7b748477b2e7c34f9ca2c952eefb7cdd10c20f6c52b2f99e781851881df26b93` |
| `anime-4.mme.txt` | `f3407aa9291498132b712c4831075fa2105d54d699cf72c89930a6dbefbfdf82` |
| `anime-4.png` | `a71f8bcefe9889c26a158a19b4548df8188401a64a6fc297da735d6af943b5a3` |
| `anime-9.mme.txt` | `1cd1044749b8746bde51f1e64ee126f6b49a8a24dbc7e406a1b15de557fcbb63` |
| `anime-9.png` | `7b748477b2e7c34f9ca2c952eefb7cdd10c20f6c52b2f99e781851881df26b93` |
| `anime.emm` | `1d1408d0e8735af536ceda13299158a9048de22e716cb4c8b09e0db07833aca3` |
| `anime.fx` | `cfde0575c6de51dd1c302c05db9fdd71596b48f78406940fe38f90d04fe40cc5` |
| `anime.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
| `control-0.mme.txt` | `0ed598f068375dbe47f6f3ee40ad73975f1a4e5df1f1447f067a3a288042dfc8` |
| `control-0.png` | `3996233707d12f86a2bfa06c7aeb31f16cfbf1f205ad2922256c217fd3fa9b5e` |
| `control-15.mme.txt` | `432afc90ac4b56cd05356cb4b3064e1327f452e7bf992fb9aa10163aee2cf86d` |
| `control-15.png` | `2c88009293516d298f99c399a1d284939df803f0fd6c9926405f5b2affc3e49e` |
| `control-30.mme.txt` | `f23c198d7b06b32fd6c9216e7cca61b5d16d70f6b1bb953a3a44d4522ed07a29` |
| `control-30.png` | `2b7849d2fa967396b1e6a7d20ce9ec7eb05e770670b3a420bad914042a09afb8` |
| `control.emm` | `2b1d1c5263ef290c67fb7de29fb4bee9d9f35267988a4e4ac316eab37e00aa2a` |
| `control.fx` | `6b628586d7bc068f3394a9c6d008ee1e7bcdc7f6deb34c76f389f39e6dbaf66c` |
| `control.pmm` | `ed1ded354446c1ec6d0a4e423dcb74f371bddf131f7f071d13118bb2c8363490` |
| `gen_mmegold.py` | `39a5e4e29aca6d3df12b1e1efac83eefdf2819544ea68137b99493061815ef94` |
| `main-0.mme.txt` | `d080348490c87431a4566e3aa4b01012b1274e27bcddb24db43a2755b08181fd` |
| `main-0.png` | `f6348db3948462b4d1fcc514513ca4aeb5258a0a5b20462fa71640dc77337293` |
| `main-30.mme.txt` | `984855ecc7f2d036169f2fa29cef12a0a70adcec09dde9899b99ebcb5513db0e` |
| `main-30.png` | `f6348db3948462b4d1fcc514513ca4aeb5258a0a5b20462fa71640dc77337293` |
| `main.emm` | `03dd1913618e161cb6e78f13ebf5fce8fe7a432dcd2d9fb5d635fe71220993ae` |
| `main.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
| `objects-0.mme.txt` | `8d24f62dd9b374a8b29b487780bc95eafbd02b08823f816a844532f4bca4d56a` |
| `objects-0.png` | `2c96d48299e3705f7f3d657afcfc2de154f72af55c2212a8c8dcb4ac750e3494` |
| `objects-30.mme.txt` | `0f3f25e012972a089d4f3a26067091dd0c56f4707a2fce7a9796418fc3a786e7` |
| `objects-30.png` | `2c96d48299e3705f7f3d657afcfc2de154f72af55c2212a8c8dcb4ac750e3494` |
| `objects.emm` | `0a32154ef62b20325f3d56bde501f19e0426af78ad40e074f12903b95a4c5e60` |
| `objects.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
| `offscreen-0.mme.txt` | `75a02248acc16060bc4a5e0049a577d9ffda1aa2c79789571a8f19f9f982bc44` |
| `offscreen-0.png` | `90b6ec1458a6a7ab20eb5436a3d14edcbb05dbdfe8f5c394e5700929007c004a` |
| `offscreen-30.mme.txt` | `c167a6ccb43225ac0abd4e4807ead4d117c9f70546e72e56a8934e12ed0b01f7` |
| `offscreen-30.png` | `90b6ec1458a6a7ab20eb5436a3d14edcbb05dbdfe8f5c394e5700929007c004a` |
| `offscreen.emm` | `aedb92908ab1cd434e4b6746fdd50a58272e77a7bdc1ba8eb5b37be7a16df3e1` |
| `offscreen.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
| `post-0.mme.txt` | `e7ca56f6e7f7e2c3330b2e16aaea6f8d30448f083cb597b544172ba914a0740e` |
| `post-0.png` | `ea477d5b28718c7c1479d4ceb2e7fc96b95a795ada6e2f8961420556d143129b` |
| `post-30.mme.txt` | `26629951be78e17021332aa8280e088b6e16e74de7cfafbf26f93e481006a798` |
| `post-30.png` | `ea477d5b28718c7c1479d4ceb2e7fc96b95a795ada6e2f8961420556d143129b` |
| `post.emm` | `1826d417abfe33c1cf8daaee0198c335966738503d2e1d20cf5af61e8aec2e0c` |
| `post.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
| `ray-0.mme.txt` | `008649ffc184c0317a0b9a20dc420ed3f7f74dfbac3d05c200818df0506b7284` |
| `ray-0.png` | `b0f2db200f901a88e6ba3df7213f6261b9d73a8dd5c9ca2568f5ad0bca3d8576` |
| `ray-30.mme.txt` | `56b4d14869ea83c0c24318778c5e0598d210b269f9d26ca019483b6e6d6e53f5` |
| `ray-30.png` | `b0f2db200f901a88e6ba3df7213f6261b9d73a8dd5c9ca2568f5ad0bca3d8576` |
| `ray.emm` | `e5832d8ff9e754f7fcc9951d555f6b391dad71bd95cea2ffdcf0408865fdc377` |
| `ray.pmm` | `308fb58e8c21cddb90e91f836deb870488eb56368f234670f5a03d68ab540047` |
| `timeofday-0.mme.txt` | `420c5a2c9a0d5cfacb57f91370d6b926758b25a870075e5738097b89cc03f0ca` |
| `timeofday-0.png` | `90b6ec1458a6a7ab20eb5436a3d14edcbb05dbdfe8f5c394e5700929007c004a` |
| `timeofday-30.mme.txt` | `d2a4c535deea522b8d5ee9233e2acc459e49ee01df26ab58fad64025ed440741` |
| `timeofday-30.png` | `90b6ec1458a6a7ab20eb5436a3d14edcbb05dbdfe8f5c394e5700929007c004a` |
| `timeofday.emm` | `8a10f8adcc433b9b162d5d5b70528a7c00d586c7e121a9ec55f981a9e8c07e9c` |
| `timeofday.pmm` | `cd17d8842da7f6b1b2bdbe2dc2517f1cdce99218988390650a3c0f796ef90bbe` |
