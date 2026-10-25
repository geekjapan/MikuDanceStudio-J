# Bulk operations (`--mds-script`, slice script2)

These scripts run the bulk key operations of the menus that
`rust/crates/mds-ops` ports through the C++ application's own handlers and
dialogs, and save a PMM and a VMD after each operation. They are the oracle
for `mds-ops` and the Rust document. The runner, the script language, and the
regenerating steps are those of `../script/README.md`; this file adds the
commands. `pmm1/` holds the PMM 0001 scripts (its own README), and
`../physscen/` the playback and physics scenarios.

## Commands

| Command | Menu or button | Dialog, as the runner fills it |
|---|---|---|
| `bias <x> <y> <z>` | menu 219, center position bias | edits 601, 602, 603 |
| `delete unused` | menu 222 | none; the box with the deleted count is answered OK |
| `shift lip <n>` | menu 225 | edit 616 |
| `delete lip` | menu 226 | none; the OK/Cancel question is answered OK |
| `register blink <start> <end>` | menu 227 | edits 618, 619; the box with the count is answered OK |
| `delete eye` | menu 228 | as 226 |
| `register all morph` | menu 229 | none |
| `reset morphs` | menu 230 | none |
| `delete eyebrow` | menu 231 | as 226 |
| `multiply camera <16 numbers>` | menu 242, camera mode only | edits 686..701: the (scale, add) pairs of eye x, y, z, target x, y, z (add in degrees), distance, fov |
| `multiply bone <12 numbers>` | menu 251 | edits 686..697: the (scale, add) pairs of position x, y, z and rotation x, y, z (add in degrees) |
| `multiply morph <scale> <add>` | menu 252 | edits 686, 687 |
| `physics frames on` / `off` | menu 275 | combo 669, item 0 ("ON (X印)") or 1 ("OFF") |
| `scale range <from> <to> <rate> <bone> <morph> <display>` | button 424 | edits 686, 687, 605 and check boxes 688, 689, 690 (`on`/`off`) |
| `answer file <path>` | none | Queues the answer of one more file dialog of the next step. That step must use every queued answer, and its info boxes are answered OK. |

A modal dialog blocks its handler in `DialogBoxParamA`, so the runner fills
it from a `WH_CALLWNDPROCRET` hook when the dialog's `WM_INITDIALOG` has
returned: `SetWindowTextA` for an edit, `BM_SETCHECK` for a check box,
`CB_SETCURSEL` and `CBN_SELCHANGE` for a combo. Then it posts the OK
button's `BN_CLICKED`, which the dialog's modal loop delivers like a click.
A step whose handler does not open its dialog fails. A dialog value may have
at most 7 characters, because `ApplyFrameRangeScale` reads its edits with an
8-byte buffer.

The answered info boxes go to `<out-dir>\messages.tsv` (`step`, `caption`,
`text`, a line break written as `\n`). The file is written only when a box
was answered.

### Saved VMD bytes 26..29

The C++ VMD writer (`src/io/vmd_save.cpp`) writes the 30-byte signature from
a 256-byte stack buffer that `sprintf_s` filled with "Vocaloid Motion Data
0002" and a NUL only, so bytes 26..29 of the file are left-over stack and
changed between two runs. The runner sets them to 0 after every `save vmd`,
for every script directory. These four bytes are the only bytes the runner
changes. The VMDs under `../script/expected/` hold 0 there too.

## Scripts

Each script builds its scene from a model and `../swing600.vmd`
(`load model`, `load vmd`; the VMD's model-name question is answered OK),
except `multiply-camera.txt`, which loads `../camera3.pmm`. They do not use
`../swing600.pmm`: it stores the model combo indices from 0, where a combo
built by `load model` starts at 1 (item 0 is the camera), so in the C++ the
item named `chain8` selects slot 1 (`morph4`) and slot 0 cannot be selected.

| Script | Menu | Scene and what it shows |
|---|---|---|
| `bias.txt` | 219 | `chain8_ik.pmx`: every key selected, bias 1.5, -2, 0.25. |
| `unused.txt` | 222 | Equal keys of 首 at 10, 20, 30 on `chain8_ik.pmx`, then equal keys of い at 520, 540, 560 on `morph4.pmx`; 7 and 6 points deleted. |
| `lipshift.txt` | 225 | `inputs/face4.pmx`: the keys of あ, shifted by -100, then by +25. |
| `facial.txt` | 226, 228, 231 | `inputs/face4.pmx`: keys at 10, 20, 30 in all four lanes, then the three deletes in turn. |
| `blink.txt` | 227 | `morph4.pmx`: frames 0..300 (3 blinks), then 300..600 (4 blinks). |
| `registerall.txt` | 229 | `morph4.pmx` at frame 100, い set to 0.75. |
| `resetmorphs.txt` | 230 | `morph4.pmx` at frame 120: あ at 0.5, reset, あ registered. |
| `multiply-camera.txt` | 242 | `camera3.pmm`, every camera key selected. |
| `multiply-bone.txt` | 251 | `chain8_ik.pmx`, every bone key selected. |
| `multiply-morph.txt` | 252 | `morph4.pmx`, every morph key selected, weight * 0.5 + 0.25. |
| `physicsframes.txt` | 275 | `chain8_ik.pmx`, every bone key selected: OFF, then ON. |
| `scalerange.txt` | 424 | `chain8_ik.pmx` frames 0..300 by 1.5 with all key kinds, then `morph4.pmx` frames 0..600 by 0.5 with morph keys only. |

`inputs/face4.pmx` is written by `inputs/gen_face4.py` (`--write`,
`--check`): `morph4.pmx` with one morph per lane, of different kinds (next
section).

## C++ behavior the outputs record

These are the behavior of the C++ handlers, kept as they are.

- **The facial menus select morphs by kind, not by lane.** 225, 226, 228,
  and 231 compare `MorphRecord::type`, and so does `PurgeMorphFrames`. The
  PMX loader (`src/model/pmx_load.cpp`) stores the PMX morph kind there
  (0 group, 1 vertex, 2 bone, 3 UV), and the PMD loader leaves it 0. So 231
  ("eyebrow") takes the vertex morphs, 228 ("eye") the bone morphs, 225 and
  226 ("lip") the UV morphs, and on a PMD model none of them finds a morph.
  `face4.pmx` has vertex morphs in the eyebrow and eye lanes (真面目,
  まばたき), a UV morph in the lip lane (あ), and a bone morph in the other
  lane (照れ), so each of the three deletes takes something different. The
  tests of `mds-ops` pass the panel bytes (`morph_type` 2, 3, 3, 3 for
  `morph4.pmx`); the C++ reads 1, 1, 1, 1 there.
- **226, 228, and 231 orphan the last key.** `PurgeMorphFrames` frees every
  key of a matching track but the last, which keeps its record and frame
  while the track head no longer reaches it. `mds-formats inspect`
  reports "record 14 is on no track" for `facial/lip-deleted.pmm` and
  `facial/eye-deleted.pmm`, and "record 12 is on no track" for
  `facial/eyebrow-deleted.pmm` (it names the first such record only).
- **225 leaves a stale `previous` link.** A dropped key is unlinked by
  rewriting the track head's `next` only, so the key after it keeps
  `previous` pointing at the freed record. `mds-formats inspect`
  reports "record 7 previous 4 != 2" for `lipshift/shift-forward.pmm` and
  `lipshift/shift-back.pmm`.
- **227 uses the CRT `rand()`.** The application never calls `srand`, so the
  MSVC generator starts at seed 1; the only other `rand()` caller in the tree
  is the gravity noise (wind) of `src/physics/physics_frame.cpp`, which is
  off in these scenes. Whether a library calls `rand()` earlier in the
  process is not checked. The blink phase byte (`blinkPhase`) starts at 0
  and carries over from the first 227 to the second in `blink.txt`.
- **230 changes the weights only.** It writes no dirty flag and no key; the
  PMM saves the current weights, so `weighted.pmm` and `reset.pmm` differ.

## Not reached

- 227 on a model without a morph named まばたき (an error box).
- 242 in model mode and the model-mode menus in camera mode: the menu items
  are grayed out there, which fails the step.
- The Cancel buttons of the dialogs and of the OK/Cancel questions.
- The camera-mode paths of 219, 222, and 225..231, which return at their mode
  gate.

## Outputs

`expected/<script>/` holds `manifest.tsv` (format: `../script/README.md`),
`messages.tsv` where a box was answered, and the saved files. A PMM saved
from a loaded model also writes `<name>.emm`, which holds the absolute model
path on the host (`C:\mds\w2-script2\repo\out\ci\build\Release\...`); nothing
else depends on the checkout.

Build: commit `164147f` of branch `w2-script2` on `nanoha-lan` (Windows, x64
Release, VS 2022, `tools/windows/build.ps1 -Testing OFF -Targets
MikuDanceStudio`), run 2026-10-26 with

    tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
        -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir> -Dir script2'

Two runs gave identical bytes for every file. The same build reran the six
scripts of `../script/` and saved the PMM, VMD, VPD, and PMD files of their
committed manifests byte for byte (the `.emm` files differ by the checkout
path).

## Files

| File | sha256 |
|---|---|
| `bias.txt` | `17ff47769808e95899751d44286f4a64b44c057df530e2368a3b434b9f15d5aa` |
| `blink.txt` | `cd732a9992f9a22d00f2c210dffd2d71670e8194b0b9917e42622f7b27fe6833` |
| `expected/bias/bias.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/bias/bias.pmm` | `11fc32c2c7ae21aadc82dfe43a84a9beb4d17caf3e5a744ef44e379e0389a1d1` |
| `expected/bias/bias.vmd` | `643956a5ecf6afde141a7559c7b2a31ac41e623ad4bf98257fb8d1ac463f5f3f` |
| `expected/bias/manifest.tsv` | `c6ea029f2f3c35301b115775212b6561383ecd5263116c62e77663fd9b8b555c` |
| `expected/blink/blink1.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/blink/blink1.pmm` | `7835bf47f81c921ea76411b6cb8816b58d0a1a1150ef06d399ac9d6218cb5852` |
| `expected/blink/blink1.vmd` | `979d28342c926a9d94669672329b83506c2944dc580d09dc18a5a0070dac0cfb` |
| `expected/blink/blink2.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/blink/blink2.pmm` | `e425277bf999b4a7227365c20ef1d8220d1533beaf3a8dd4ace4ca40705f4673` |
| `expected/blink/blink2.vmd` | `1553f445e91cac310ed53c9e875f13f3cf8285998b2842202ce57a9c6f27b42a` |
| `expected/blink/manifest.tsv` | `46b53dfa56115577d47bf4471f942ed2d4e3bb91f4a321e3948bd3c5e5df3b30` |
| `expected/blink/messages.tsv` | `0e0b1b62542399f57e66e3afb33d7515a636573a51602b1e1f9a799a0ee00e88` |
| `expected/facial/eye-deleted.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/facial/eye-deleted.pmm` | `7d1dc5dc8edc68061a7f6dd44f583c81a579f06834406adde4270b2205c53f79` |
| `expected/facial/eye-deleted.vmd` | `f1d3cfad21c1eab4308a7e4c075336a9aed60fdec7a5482192ef16bb63aa8a6e` |
| `expected/facial/eyebrow-deleted.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/facial/eyebrow-deleted.pmm` | `b5e92d7bdc37bee04ee536d5e48ddd525bbceabe10ac0434ff5e2dcf9de88712` |
| `expected/facial/eyebrow-deleted.vmd` | `fb07a963a4c43c519eefa58c56948ffc36193edc24154771c8334e8236fb9fdc` |
| `expected/facial/lip-deleted.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/facial/lip-deleted.pmm` | `eb22740dd4215350c8e50a96577570fcc61d0dca5f70f6a3ae5a09623d4791e8` |
| `expected/facial/lip-deleted.vmd` | `72aa4157c0cd68826b9682af4b2449330a0b88bd76c6d53270ad6b2ed475f16e` |
| `expected/facial/manifest.tsv` | `ddf674477a137a2086cacac5ab598a641b7b023295ec97c4c360f35409fc6ca3` |
| `expected/facial/registered.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/facial/registered.pmm` | `7efe88e5d505e8618bde8248ce72627aa86480afa4251bd3c83f29bd9ff8e305` |
| `expected/facial/registered.vmd` | `3e92d9720b776a24aa815c2e2df6763a5cec5069b62b1f846f337f344cbb7d5d` |
| `expected/lipshift/manifest.tsv` | `6e0c5b65791ddfc952259be9b05d82ad90f536b1b582f2843b270c65415b75f3` |
| `expected/lipshift/shift-back.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/lipshift/shift-back.pmm` | `d92216e95d6e3b6c662504b6d189ccddf12a9e8130d60407cfcab32a7d9fa940` |
| `expected/lipshift/shift-back.vmd` | `df0fbb2388cbe1c3ad61199d7d4ccbc2a84f8b94f760cda721e0978003e2d07c` |
| `expected/lipshift/shift-forward.emm` | `ff387f62af7ec4a3afcd26d772327db1cb8bf30b4177cb21224bd52a83ecf053` |
| `expected/lipshift/shift-forward.pmm` | `9ef9534a31b6a6225f7faa5e01f3cf0d0ea379a0441b6ed56c8dc07d46cb8360` |
| `expected/lipshift/shift-forward.vmd` | `4c5f3fd2f4e9acfb8e5374ddfdf8dfc8f28d1e4e7dc77a757218333e64edd900` |
| `expected/multiply-bone/manifest.tsv` | `8cb6b61a4fb245a1534c10195684eb35987dc1f501bb1e20a72f4624f55b7240` |
| `expected/multiply-bone/multiplied.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/multiply-bone/multiplied.pmm` | `aee325c88cbe7ec5368f029c75fc635d3157f678a5bce2253b5f4e5db700d42b` |
| `expected/multiply-bone/multiplied.vmd` | `00fd6bcba84cf01fc68f4eec40b148a8689f5152a537bfb39fbc59d3fed2fc0b` |
| `expected/multiply-camera/manifest.tsv` | `df258c83e5fdf141edc4c848fa08970d361731c9a2b3ba92c063753e6ca947c1` |
| `expected/multiply-camera/multiplied.emm` | `9e3c22685289ca078ec4cb58bc01ea592e8be71b72bdfdd1212998cf81cdda0a` |
| `expected/multiply-camera/multiplied.pmm` | `e1452210ad1f0dd6ac50732bddacc0eb0b9ed0e17955f553f4014ca2fc4978bc` |
| `expected/multiply-camera/multiplied.vmd` | `1119416e6edb396413c1a96967be943393e5bf574dff8bf10fd3b0b6ab96af84` |
| `expected/multiply-morph/manifest.tsv` | `6849e50b2ebcf849861eadc4c7429b2d11af5b318a5c1d71579da789e19ca69d` |
| `expected/multiply-morph/multiplied.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/multiply-morph/multiplied.pmm` | `103909c9456f2a988518ea0c40dc2fe7142e36aee3d540ff349b64e2f03c95d5` |
| `expected/multiply-morph/multiplied.vmd` | `76b04d55d1bba18a504b29f7fcf887d37e829674277f7aec67cf2488d8f43ce5` |
| `expected/physicsframes/manifest.tsv` | `67cbe3e828a2561b662ea2f0e54fa34184f8905270b2feb7bba338de44c53f11` |
| `expected/physicsframes/physics-off.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/physicsframes/physics-off.pmm` | `c994629463d1ada12e80e9a4aed3e77e7432fc4f0785a56ba57a73dcf3d4c15d` |
| `expected/physicsframes/physics-off.vmd` | `9a6756868cf8124530ba19a1ac19f1259bbf2a3727f662add9fb9f824377e6a8` |
| `expected/physicsframes/physics-on.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/physicsframes/physics-on.pmm` | `a7aa3d313145c2c82108d6aa9bfe1c9e6a1909454b5a56b9a6d560793db9487a` |
| `expected/physicsframes/physics-on.vmd` | `af01ae276d9725cebcbd18bdca63d6d81edc2d48b4f6fb6d1d7492e606b27cb6` |
| `expected/registerall/manifest.tsv` | `28872dfd106f19dbc9477f45b8e4278b27644950312188f5cdaac9f6b9730e9c` |
| `expected/registerall/registered-all.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/registerall/registered-all.pmm` | `f6c138fa3a4bba7615473a71791a7b5164df6c214a68848624685ad32661489a` |
| `expected/registerall/registered-all.vmd` | `709c486fd4aea24548a3939766dcb70949382cb2d6dcbb60753991f2be989948` |
| `expected/resetmorphs/manifest.tsv` | `cce020e42fe9ee107a3fb6a4ebd344ba0cf2515a852af6d65d3ad93855cfed1e` |
| `expected/resetmorphs/registered.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/resetmorphs/registered.pmm` | `199f7dd6eb6a59a1b1b5c9df0366bbee43c1e60b1484d5949bea4db88af20360` |
| `expected/resetmorphs/registered.vmd` | `77159eca93eb1c35ef4f9da01b1fa86acac23dbdfa7d9629848ae1e50672cdd6` |
| `expected/resetmorphs/reset.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/resetmorphs/reset.pmm` | `5bb4c7f978cba2ea6a7871bc51cd27f0a21cdfedda83d8d05bbcc830eb6dd94e` |
| `expected/resetmorphs/weighted.emm` | `174cd70a7aee9eae0a3c423500d249febb8363063b11d8d60243c754059d0681` |
| `expected/resetmorphs/weighted.pmm` | `765e9764ed66d7673999bd1e32af36991fde2f6b32dcb3294e4317775c13d79f` |
| `expected/scalerange/manifest.tsv` | `20de96351a63c0bce9adfcc90d6b7767e55911912f25dd3ab7b07d0b6a4bdcb9` |
| `expected/scalerange/scaled-chain8.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/scalerange/scaled-chain8.pmm` | `a26b3e0f63d08853149fe1c7fdefc561843d3948f9b5c14e36c381da304cba0d` |
| `expected/scalerange/scaled-chain8.vmd` | `5bd113e3ba6af36049898b6b5b27301ee26b86b74d614c87da8806045fa8617b` |
| `expected/scalerange/scaled-morph4.emm` | `211dc8be6d6e6274d7b3f56163cfc186ddf0db58b0e8fd647c660064e99a05c0` |
| `expected/scalerange/scaled-morph4.pmm` | `9e78f327408f6baf69bee679a2d7b48b2ec3b1e57726f65be7651658ad1cbc7f` |
| `expected/scalerange/scaled-morph4.vmd` | `2c89ca84609e79dce678f9b9b8f771ddcbe1c8f02ab9ee901b96ce202a811d70` |
| `expected/unused/keys-chain8.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/unused/keys-chain8.pmm` | `da8431a6e50777d417ee8772aedc3a989b917e3209e693fee671857ffdbf9dd1` |
| `expected/unused/keys-morph4.emm` | `211dc8be6d6e6274d7b3f56163cfc186ddf0db58b0e8fd647c660064e99a05c0` |
| `expected/unused/keys-morph4.pmm` | `0440a265ed1db1402c2b81961dee53b4a313e175e81fd0501e5a7d93a206a949` |
| `expected/unused/manifest.tsv` | `2a3440fe2e45c5dcd4def0a6b954f436406d495196567032888d308753e8f06d` |
| `expected/unused/messages.tsv` | `0560dec37305c2ee9d031f4e50d7491dd982247523be0d3083eb9239c7feae37` |
| `expected/unused/unused-chain8.emm` | `dd08b6f950dbc57dc3bb1d8b9b89bf4beaf95b6005bb69e9554bd94760140d69` |
| `expected/unused/unused-chain8.pmm` | `d2e8ee7a76d85df4801e1c3aee017499dfbdaef896bf1ada10073b6458bbea2d` |
| `expected/unused/unused-chain8.vmd` | `953226cccc509b70e179fa81f15876f769b51946e6abdd126facd8353735ab2c` |
| `expected/unused/unused-morph4.emm` | `211dc8be6d6e6274d7b3f56163cfc186ddf0db58b0e8fd647c660064e99a05c0` |
| `expected/unused/unused-morph4.pmm` | `a25a1ead2d899208a7a9fe1e9469e7276ea1cde860fdb511586485af2379ddad` |
| `expected/unused/unused-morph4.vmd` | `021b9323fa14fab8eea9c1049902f6fc69ca5a037fe9b8220afa80553259c079` |
| `facial.txt` | `312666547bb9fe573c3ea33ad7641f631b228cd83b16c778ab6f5f0c6e9305f9` |
| `inputs/face4.pmx` | `7138498eb5190b25b862f20746bfea77d74d5fd46b6eaac6ca4b7f387a3461a5` |
| `inputs/gen_face4.py` | `c6948aba3cea51614efcb67d4fdb10a396bd7997b944ec1f4d87e8fa8db96ec7` |
| `lipshift.txt` | `02bdeb5afa85a1a73e2cdf37b04acce8946f0fbcbd02cd1620e0fd193d9f973a` |
| `multiply-bone.txt` | `9c5cbf33c5b43d199a6f8002aea88542d2337b1fbcc973400f86ae67a80333cc` |
| `multiply-camera.txt` | `36f2907642c61c4563760875d2b9a1e0a099bd9e399ac743e127463fea17b8f1` |
| `multiply-morph.txt` | `abe98d99be2c535af3661c59eb0a13b1ac76b6ed61b86d5d6951b14a746ebb25` |
| `physicsframes.txt` | `38241b3448cbce491cd63ffb06d4e539feb8709e18f9ca1733b473bae56498d5` |
| `registerall.txt` | `2b20141f177d783f692ff3c0c0073c030727b554f5b979721f2b2efb2070f0c5` |
| `resetmorphs.txt` | `004bc5af1ef6eafcc94c3bbf8bd981a42f9b427928f481af63c6496a91504a3e` |
| `scalerange.txt` | `b3ef50bf87d40aa01fbe0fbe941deec6d086fbf82bb993b8a267b187a640968c` |
| `unused.txt` | `cf7bda8abcc6d8b1ffa11238126b3fc76a57e1b2cb5b9446798a1f62c611a2d1` |
