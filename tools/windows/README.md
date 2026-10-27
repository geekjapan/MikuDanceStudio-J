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

## Capture-only VC90 provisioning

`provision_capture_vc90.ps1` runs only in the GitHub-hosted Windows x64 job
with `d3d9-capture` enabled. It does not provision a developer or persistent
Windows host. Generic CI keeps its existing dependency setup.

The helper downloads the fixed Microsoft VC2008 SP1 x64 9.0.30729.6161
package to a unique `RUNNER_TEMP` directory. It requires 5,211,080 bytes,
SHA256 `C5E273A4A16AB4D5471E91C7477719A2F45DDADB76C7F98A38FA5074A6838654`,
and Windows Authenticode `Valid` with signer `Microsoft Corporation` before
execution. The [pinned Microsoft winget manifest](https://raw.githubusercontent.com/microsoft/winget-pkgs/4893071f9898d6275f4cdae5e2ed0af2c474dbde/manifests/m/Microsoft/VCRedist/2008/x64/9.0.30729.6161/Microsoft.VCRedist.2008.x64.installer.yaml)
supplies the fixed URL, hash, and `/qn /norestart /l "<log>"` flags. The
helper does not apply winget's uninstall-previous behavior.

The installer wait is 120 seconds. Timeout cleanup terminates and reaps only
the directly owned process with a further ten-second bound. It never stops
a shared installer service or unrelated process. Exit 3010 records a restart
request, and 1638 records an existing-version conflict. Both fail provisioning.
The helper never reboots, uninstalls, or downgrades a runtime.

`out/d3d9-capture/vc90-provisioning/` retains the download and exact command
receipt, full Authenticode serialization, stdout, stderr, installer-generated
log when available, and installed amd64 CRT/OpenMP XML. `policy.json` records
identities, redirect ranges, target manifests, and target directories. Both
families must redirect requested version `9.0.21022.8` to a present target.
[Microsoft's publisher configuration documentation](https://learn.microsoft.com/en-us/windows/win32/sbscs/publisher-configuration-files)
defines these version redirects. Missing policy evidence fails provisioning.
No installer or runtime DLL is copied into application or capture artifacts.

Provisioning never reports application activation success. The existing
`always()` capture still runs after a provisioning failure. Its original
FAIL, SideBySide diagnostics, source/staged closure, process-start receipts,
output validation, and frame/mask thresholds remain authoritative. Policy
presence and installer exit zero cannot replace unchanged-app startup and
rendered output. A later activation or rendering failure remains possible.

Run `python -I tools/windows/test_provision_capture_vc90.py` and the same
command with `-O` for local boundary checks. These use fake downloads and
signatures, real stand-in subprocesses, and fixture policy XML. They do not
validate Windows trust, install the package, or exercise native rendering.
