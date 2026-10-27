param([string]$Receipts)
$ErrorActionPreference = 'Stop'

function Get-Vc90PolicyEvidence {
    param([string]$Destination)
    $sxs = Join-Path $env:WINDIR 'WinSxS'
    $files = @(Get-ChildItem (Join-Path $sxs 'Manifests') -Filter 'amd64_*microsoft.vc90.*.manifest' -File)
    foreach ($directory in Get-ChildItem $sxs -Filter 'amd64_policy.9.0.microsoft.vc90.*' -Directory) {
        $files += @(Get-ChildItem $directory.FullName -File)
    }
    $records = @()
    foreach ($file in $files | Sort-Object FullName -Unique) {
        if ($file.FullName -notmatch '(?i)vc90\.(crt|openmp)_|vc90\.(crt|openmp)\.policy$') { continue }
        $raw = Get-Content $file.FullName -Raw
        try { $xml = [xml]$raw } catch { throw "Invalid installed policy/assembly XML '$($file.FullName)': $_" }
        $identity = $xml.SelectSingleNode('/*[local-name()="assembly"]/*[local-name()="assemblyIdentity"]')
        if (-not $identity -or $xml.DocumentElement.NamespaceURI -cne 'urn:schemas-microsoft-com:asm.v1') { continue }
        $copy = Join-Path $Destination ('installed-' + $records.Count + '.xml')
        Copy-Item $file.FullName $copy
        $redirects = @($xml.SelectNodes('//*[local-name()="dependentAssembly"]') | ForEach-Object {
            $dependency = $_.SelectSingleNode('*[local-name()="assemblyIdentity"]')
            foreach ($redirect in $_.SelectNodes('*[local-name()="bindingRedirect"]')) {
                [ordered]@{ name = $dependency.GetAttribute('name'); architecture = $dependency.GetAttribute('processorArchitecture')
                    token = $dependency.GetAttribute('publicKeyToken'); type = $dependency.GetAttribute('type')
                    old_version = $redirect.GetAttribute('oldVersion'); target_version = $redirect.GetAttribute('newVersion') }
            }
        })
        $records += [ordered]@{ source = $file.FullName; copy = $copy; sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
            name = $identity.GetAttribute('name'); architecture = $identity.GetAttribute('processorArchitecture')
            token = $identity.GetAttribute('publicKeyToken'); type = $identity.GetAttribute('type')
            version = $identity.GetAttribute('version'); redirects = $redirects
            assembly_directory = $(if ($file.Extension -eq '.manifest') { Join-Path $sxs $file.BaseName } else { $null }) }
    }
    $compatible = @()
    foreach ($name in @('Microsoft.VC90.CRT', 'Microsoft.VC90.OpenMP')) {
        $matches = @()
        foreach ($policy in $records) {
            if ($policy.name -ine "policy.9.0.$name" -or $policy.architecture -ine 'amd64' -or
                $policy.token -ine '1fc8b3b9a1e18e3b' -or $policy.type -cne 'win32-policy') { continue }
            foreach ($redirect in $policy.redirects) {
                if ($redirect.name -ine $name -or $redirect.architecture -ine 'amd64' -or
                    $redirect.token -ine '1fc8b3b9a1e18e3b' -or $redirect.type -cne 'win32') { continue }
                $range = $redirect.old_version.Split('-')
                $low = [version]$range[0]
                $high = if ($range.Count -eq 2) { [version]$range[1] } else { $low }
                if ($range.Count -gt 2 -or [version]'9.0.21022.8' -lt $low -or [version]'9.0.21022.8' -gt $high) { continue }
                $targets = @($records | Where-Object { $_.name -ieq $name -and $_.architecture -ieq 'amd64' -and
                    $_.token -ieq '1fc8b3b9a1e18e3b' -and $_.type -ceq 'win32' -and $_.version -eq $redirect.target_version -and
                    (Test-Path $_.assembly_directory -PathType Container) })
                foreach ($target in $targets) {
                    $matches += [ordered]@{ policy = $policy.source; old_version = $redirect.old_version
                        target_version = $redirect.target_version; target_manifest = $target.source; target_directory = $target.assembly_directory }
                }
            }
        }
        $compatible += [ordered]@{ name = $name; requested_version = '9.0.21022.8'; matches = $matches }
    }
    $evidence = [ordered]@{ assemblies = $records; compatibility = $compatible
        status = $(if (@($compatible | Where-Object { $_.matches.Count -eq 0 }).Count) { 'UNPROVEN' } else { 'POLICY_AND_TARGET_PRESENT' })
        activation = 'NOT_EVALUATED; unchanged application capture remains authoritative' }
    $evidence | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $Destination 'policy.json') -Encoding utf8
    if ($evidence.status -ne 'POLICY_AND_TARGET_PRESENT') { throw 'Installed amd64 CRT/OpenMP publisher policy compatibility is unproven' }
}

function Install-CaptureVc90 {
    param([string]$Destination, [string]$ArchiveDirectory, [int]$TimeoutSeconds = 120)
    New-Item -ItemType Directory $Destination -ErrorAction Stop | Out-Null
    $archive = Join-Path $ArchiveDirectory 'vcredist_x64.exe'
    $log = Join-Path $Destination 'installer.log'
    $receipt = [ordered]@{ schema = 1; status = 'FAIL'; activation = 'NOT_EVALUATED'
        url = 'https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x64.exe'
        manifest = 'https://raw.githubusercontent.com/microsoft/winget-pkgs/4893071f9898d6275f4cdae5e2ed0af2c474dbde/manifests/m/Microsoft/VCRedist/2008/x64/9.0.30729.6161/Microsoft.VCRedist.2008.x64.installer.yaml'
        version = '9.0.30729.6161'; expected_size = 5211080
        expected_sha256 = 'C5E273A4A16AB4D5471E91C7477719A2F45DDADB76C7F98A38FA5074A6838654'
        download_command = @('Invoke-WebRequest', '-Uri', '', '-OutFile', $archive, '-TimeoutSec', '120', '-PassThru')
        command = @($archive, '/qn', '/norestart', '/l', $log); timeout_seconds = $TimeoutSeconds
        started_utc = [DateTime]::UtcNow.ToString('o'); process_started = $false; pid = $null
        returncode = $null; timed_out = $false; cleanup_error = $null; error = $null }
    $receipt.download_command[2] = $receipt.url
    $process = $null
    try {
        $download = Invoke-WebRequest -Uri $receipt.url -OutFile $archive -TimeoutSec 120 -PassThru
        $receipt.download = [ordered]@{ status_code = $download.StatusCode; headers = $download.Headers
            final_uri = [string]$download.BaseResponse.RequestMessage.RequestUri }
        $receipt.size = (Get-Item $archive).Length
        $receipt.sha256 = (Get-FileHash $archive -Algorithm SHA256).Hash
        if ($receipt.size -ne $receipt.expected_size -or $receipt.sha256 -cne $receipt.expected_sha256) {
            throw 'Unexpected VC2008 SP1 x64 payload size or SHA256'
        }
        $signature = Get-AuthenticodeSignature -FilePath $archive
        $signature | Export-Clixml (Join-Path $Destination 'authenticode.clixml')
        $signature | Format-List * | Out-String -Width 4096 | Set-Content (Join-Path $Destination 'authenticode.txt') -Encoding utf8
        $receipt.signature = [ordered]@{ status = [string]$signature.Status; message = $signature.StatusMessage
            subject = $signature.SignerCertificate.Subject; thumbprint = $signature.SignerCertificate.Thumbprint
            timestamp_subject = $signature.TimeStamperCertificate.Subject }
        if ([string]$signature.Status -cne 'Valid' -or -not $signature.SignerCertificate -or
            $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -cne 'Microsoft Corporation') {
            throw 'VC2008 SP1 Authenticode must be Valid and signed by Microsoft Corporation'
        }
        $process = Start-Process -FilePath $archive -ArgumentList @('/qn', '/norestart', '/l', ('"{0}"' -f $log)) -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Destination 'stdout.txt') -RedirectStandardError (Join-Path $Destination 'stderr.txt')
        $receipt.process_started = $true
        $receipt.pid = $process.Id
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $receipt.timed_out = $true
            throw "VC2008 SP1 installer exceeded $TimeoutSeconds seconds"
        }
        $receipt.returncode = $process.ExitCode
        $receipt.installer_result = switch ($process.ExitCode) {
            0 { 'COMPLETED' }
            3010 { 'RESTART_REQUIRED; no reboot performed' }
            1638 { 'EXISTING_VERSION_CONFLICT; no uninstall or downgrade performed' }
            default { 'FAILED' }
        }
        if ($process.ExitCode -ne 0) {
            try { Get-Vc90PolicyEvidence -Destination $Destination } catch { $receipt.policy_error = [string]$_ }
            throw "VC2008 SP1 installer exit $($process.ExitCode): $($receipt.installer_result)" }
        Get-Vc90PolicyEvidence -Destination $Destination
        $receipt.status = 'PROVISIONED; activation not evaluated'
    } catch {
        $receipt.error = [string]$_
        throw
    } finally {
        if ($process) {
            try {
                if (-not $process.HasExited) {
                    $process.Kill()
                    if (-not $process.WaitForExit(10000)) { throw 'Owned installer did not exit after termination' }
                }
                $receipt.returncode = $process.ExitCode
            } catch { $receipt.cleanup_error = [string]$_ } finally { $process.Dispose() }
        }
        if ($receipt.timed_out) {
            try { Get-Vc90PolicyEvidence -Destination $Destination } catch { $receipt.policy_error = [string]$_ }
        }
        $receipt.finished_utc = [DateTime]::UtcNow.ToString('o')
        $receipt | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Destination 'receipt.json') -Encoding utf8
        if ($receipt.cleanup_error) { throw $receipt.cleanup_error }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not $IsWindows -or $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
        $env:RUNNER_OS -cne 'Windows' -or $env:RUNNER_ARCH -cne 'X64' -or $env:MDS_D3D9_CAPTURE -cne '1') {
        throw 'VC90 provisioning is restricted to the ephemeral GitHub-hosted Windows x64 capture job'
    }
    if (-not $Receipts) { throw 'Receipts directory is required' }
    $archiveDirectory = Join-Path $env:RUNNER_TEMP ('mds-vc90-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $archiveDirectory | Out-Null
    Install-CaptureVc90 -Destination $Receipts -ArchiveDirectory $archiveDirectory
}
