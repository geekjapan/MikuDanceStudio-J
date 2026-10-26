# Windows host scripts

Scripts for the Windows lanes on the host that gate G2 names. Copy this
directory to the host, for example to `C:\mds\w2-<id>\scripts`, and run each
script with `powershell -NoProfile -ExecutionPolicy Bypass -File`.

| Script | Use |
|---|---|
| `env.ps1` | Dot-source. Loads VS Build Tools 2022 x64, CMake, the conan venv in `C:\mds-tools\conan-venv`, Git, and cargo. |
| `build.ps1 -Root <checkout>` | Runs conan and CMake and builds `out/ci/build` in Release. |
| `stage.ps1 -Root <checkout>` | Copies the fixture models next to the exe. Run it before a lane opens a PMM. |
| `runtask.ps1 -Script <x.ps1> -Log <x.log> [-Exclusive]` | Runs a script in the console session and reports its full exit code. Returns 0 for success, preserves failures 1 through 255, and maps other failures to 1 so SSH and POSIX callers cannot mistake them for success. Timeout, invalid/missing completion status, and scheduler errors fail the command. GUI and D3D9 lanes need it. Add `-Exclusive` when the script sends keyboard or mouse input. |

Each slice uses its own checkout under `C:\mds\w2-<id>\`, so slices never
share a build tree. `tools/oracle/gui_save.ps1` is an example of a lane that
needs `runtask.ps1 -Exclusive`.

On timeout, the helper attempts `schtasks /End` before cleanup. If that command
fails, the helper fails and retains its exact task registration and wrapper.
Its warning includes the task name, wrapper, log, completion file, and recovery
command. The helper releases its mutex on exit. Confirm that the retained task
has stopped before deleting its registration and wrapper or starting another
exclusive lane.
