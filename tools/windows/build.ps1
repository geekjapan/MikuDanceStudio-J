# Build MikuDanceStudio in a checkout on the Windows host.
# Usage: build.ps1 -Root C:\mds\w2-<id>\repo [-Testing ON|OFF] [-Targets a,b]
param([Parameter(Mandatory)][string]$Root, [string]$Testing = 'ON', [string]$Targets = '')
. "$PSScriptRoot\env.ps1"
$ErrorActionPreference = 'Continue'
Set-Location $Root
"== build $Root testing=$Testing targets=$Targets  $(Get-Date -Format o)"
git rev-parse HEAD
$conan = @('--profile:all', 'profiles/x64', '-s', 'compiler.cppstd=17', '-s', 'build_type=Release', '-s', 'compiler.version=194', '--build=missing', '--lockfile=')
conan create recipes/bullet275 @conan
"conan create exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 10 }
conan install . @conan --output-folder=out/ci
"conan install exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 11 }
cmake -S . -B out/ci/build -G "Visual Studio 17 2022" -A x64 "-DCMAKE_TOOLCHAIN_FILE=$PWD/out/ci/build/generators/conan_toolchain.cmake" -DBUILD_TESTING=$Testing -DMIKUDANCESTUDIO_DIAG=OFF
"cmake configure exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 12 }
$build = @('--build', 'out/ci/build', '--config', 'Release', '--parallel', '12')
if ($Targets) { $build += @('--target') + $Targets.Split(',') }
cmake @build -- /nologo /v:minimal
"cmake build exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 13 }
"== done $(Get-Date -Format o)"
