# dot-source: sets up VS2022 BuildTools x64 env, cmake, ninja, conan, git, cargo
$env:VSCMD_SKIP_SENDTELEMETRY="1"
$vs='C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$tmp = cmd /c "`"$vs\VC\Auxiliary\Build\vcvars64.bat`" >nul && set"
foreach ($l in $tmp) { if ($l -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($matches[1])" -Value $matches[2] } }
$env:Path = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;C:\mds-tools\conan-venv\Scripts;C:\Program Files\Git\cmd;C:\Python314;$env:USERPROFILE\.cargo\bin;$env:Path"
[Console]::OutputEncoding=[Text.Encoding]::UTF8
