param([string]$Receipts)
$ErrorActionPreference = 'Stop'

function Get-Vc90MsiDestinationObservation {
    param([string]$Destination)
    $assembly = 'amd64_microsoft.vc90.openmp_1fc8b3b9a1e18e3b_9.0.30729.6161_none_390d35aa0a1f21f9'
    $policy = 'amd64_policy.9.0.microsoft.vc90.openmp_1fc8b3b9a1e18e3b_9.0.30729.6161_none_c6e675e4a2af6563'
    # Fixed destinations from the retained MSI SetTargetFolder/AssemblyCopy operations, never log-supplied paths.
    $paths = @($assembly, $policy,
        "$assembly/amd64_Microsoft.VC90.OpenMP_1fc8b3b9a1e18e3b_9.0.30729.6161_x-ww_7fe65c7f.manifest",
        "$policy/9.0.30729.6161.policy", "$assembly/vcomp90.dll")
    $observation = [ordered]@{ schema = 1; status = 'OBSERVATION_ONLY'; activation = 'NOT_EVALUATED'
        version = '9.0.30729.6161'; windir = $env:WINDIR; pshome = $PSHOME
        process_path = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        is_64bit_os = [Environment]::Is64BitOperatingSystem; is_64bit_process = [Environment]::Is64BitProcess
        installer_log = $null; entries = @() }
    function Read-Vc90LiteralItem([string]$Path) {
        # Inspect each ancestor before following it, including WINDIR and WinSxS themselves.
        $parents = @()
        $parent = [IO.Path]::GetDirectoryName($Path)
        while ($parent) {
            $parents = @($parent) + $parents
            $parent = [IO.Path]::GetDirectoryName($parent)
        }
        foreach ($candidate in $parents + @($Path)) {
            $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refused reparse point: $candidate"
            }
        }
        return $item
    }
    foreach ($relative in $paths) {
        $record = [ordered]@{ relative_path = $relative; path = $null; status = 'UNKNOWN'; exists = $null
            metadata = $null; sha256 = $null; copy = $null; error = $null }
        try {
            $record.path = Join-Path (Join-Path $env:WINDIR 'WinSxS') $relative
            $item = Read-Vc90LiteralItem $record.path
            $record.exists = $true
            $record.metadata = [ordered]@{ path = $item.FullName; attributes = [string]$item.Attributes
                attributes_value = [int]$item.Attributes; directory = $item.PSIsContainer
                size = $(if ($item.PSIsContainer) { $null } else { $item.Length })
                last_write_utc = $item.LastWriteTimeUtc.ToString('o') }
            if ($item.PSIsContainer -ne ($relative -in @($assembly, $policy))) { throw 'Unexpected MSI destination item type' }
            if (-not $item.PSIsContainer) {
                $record.sha256 = (Get-FileHash -LiteralPath $record.path -Algorithm SHA256 -ErrorAction Stop).Hash
                if ([IO.Path]::GetExtension($relative) -in @('.manifest', '.policy')) {
                    $record.copy = Join-Path $Destination ('msi-destination-' + $observation.entries.Count + '.xml')
                    Copy-Item -LiteralPath $record.path -Destination $record.copy -ErrorAction Stop
                    if ((Get-FileHash -LiteralPath $record.copy -Algorithm SHA256 -ErrorAction Stop).Hash -cne $record.sha256) {
                        throw 'MSI destination changed during copy'
                    }
                }
            }
            $record.status = 'PRESENT'
        } catch [System.Management.Automation.ItemNotFoundException] {
            $record.exists = $false; $record.status = 'MISSING'; $record.error = [string]$_
        } catch { $record.error = [string]$_ }
        $observation.entries += $record
    }
    $log = [ordered]@{ source = (Join-Path $Destination 'installer.log'); sha256 = $null; size = $null
        status = 'UNKNOWN'; error = $null }
    try {
        $item = Read-Vc90LiteralItem $log.source
        if ($item.PSIsContainer) { throw 'Installer log must be a file' }
        $log.size = $item.Length
        $log.sha256 = (Get-FileHash -LiteralPath $log.source -Algorithm SHA256 -ErrorAction Stop).Hash
        $log.status = 'PRESENT'
    } catch { $log.error = [string]$_ }
    $observation.installer_log = $log
    $observation | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Destination 'msi-destinations.json') -Encoding utf8
}

function Get-Vc90PolicyEvidence {
    param([string]$Destination)
    function Read-Vc90Version([string]$Value) {
        if ($Value -cnotmatch '^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}$' -or
            @($Value.Split('.') | Where-Object { [int]$_ -gt 65535 }).Count) {
            throw "Invalid four-part SxS version '$Value'"
        }
        return [version]$Value
    }
    function Get-Vc90EntryMetadata($Entry) {
        [ordered]@{ path = $Entry.FullName; name = $Entry.Name; attributes = [string]$Entry.Attributes
            attributes_value = [int]$Entry.Attributes; directory = $Entry.PSIsContainer
            size = $(if ($Entry.PSIsContainer) { $null } else { $Entry.Length }) }
    }
    $sxs = Join-Path $env:WINDIR 'WinSxS'
    $files = @()
    $errors = @()
    $enumerations = @()
    foreach ($family in @('crt', 'openmp')) {
        $manifests = Join-Path $sxs 'Manifests'
        foreach ($prefix in @("amd64_microsoft.vc90.${family}_", "amd64_policy.9.0.microsoft.vc90.${family}_")) {
            $query = [ordered]@{ root = $manifests; filter = "$prefix*.manifest"; kind = 'File'; force = $true
                exists = $null; entries = @(); error = $null }
            $enumerations += $query
            try {
                $query.exists = Test-Path $manifests -PathType Container
                if ($query.exists) {
                    $entries = @(Get-ChildItem $manifests -Filter $query.filter -File -Force)
                    $query.entries = @($entries | ForEach-Object { Get-Vc90EntryMetadata $_ })
                    $files += $entries
                }
            } catch { $query.error = [string]$_; $errors += "$manifests`: $_" }
        }
        foreach ($store in @($sxs, (Join-Path $sxs 'Policies'))) {
            $query = [ordered]@{ root = $store; filter = "amd64_policy.9.0.microsoft.vc90.${family}_*"; kind = 'Directory'; force = $true
                exists = $null; entries = @(); error = $null }
            $enumerations += $query
            try {
                $query.exists = Test-Path $store -PathType Container
                if (-not $query.exists) { continue }
                $directories = @(Get-ChildItem $store -Filter $query.filter -Directory -Force)
                $query.entries = @($directories | ForEach-Object { Get-Vc90EntryMetadata $_ })
            } catch { $query.error = [string]$_; $errors += "$store`: $_"; continue }
            foreach ($directory in $directories) {
                $query = [ordered]@{ root = $directory.FullName; filter = '*.policy'; kind = 'File'; force = $true
                    exists = $null; entries = @(); error = $null }
                $enumerations += $query
                try {
                    $query.exists = Test-Path $directory.FullName -PathType Container
                    $entries = @(Get-ChildItem $directory.FullName -Filter '*.policy' -File -Force)
                    $query.entries = @($entries | ForEach-Object { Get-Vc90EntryMetadata $_ })
                    $files += $entries
                } catch { $query.error = [string]$_; $errors += "$($directory.FullName): $_" }
            }
        }
    }
    $enumerations | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Destination 'discovery.json') -Encoding utf8
    $records = @()
    foreach ($file in $files | Sort-Object FullName -Unique) {
        $copy = Join-Path $Destination ('installed-' + $records.Count + '.xml')
        Copy-Item $file.FullName $copy
        $record = [ordered]@{ source = $file.FullName; copy = $copy; sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
            name = $null; architecture = $null; token = $null; type = $null; version = $null; redirects = @()
            assembly_directory = $(if ($file.Extension -eq '.manifest') { Join-Path $sxs $file.BaseName } else { $null })
            valid = $false; error = $null }
        try {
            $xml = [xml](Get-Content $file.FullName -Raw)
            $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
            $ns.AddNamespace('a', 'urn:schemas-microsoft-com:asm.v1')
            $ns.AddNamespace('h', 'urn:schemas-microsoft-com:asm.v2')
            $isPolicy = $file.Name -like 'amd64_policy.*' -or $file.Extension -ieq '.policy'
            $invalidNamespaces = if ($isPolicy) {
                $xml.SelectNodes('//*[namespace-uri() != "urn:schemas-microsoft-com:asm.v1"]').Count
            } else {
                # Original Microsoft targets carry asm.v2 hashes with XMLDSIG descendants beneath files.
                $xml.SelectNodes('//*[namespace-uri() != "urn:schemas-microsoft-com:asm.v1" and
                    not(self::h:hash[parent::a:file[parent::a:assembly]]) and
                    not(namespace-uri() = "http://www.w3.org/2000/09/xmldsig#" and
                        ancestor::h:hash[parent::a:file[parent::a:assembly]])]', $ns).Count
            }
            $root = $xml.DocumentElement
            $identities = $xml.SelectNodes('/a:assembly/a:assemblyIdentity', $ns)
            if ($root.LocalName -cne 'assembly' -or $root.NamespaceURI -cne $ns.LookupNamespace('a') -or
                $root.GetAttribute('manifestVersion') -cne '1.0' -or $identities.Count -ne 1 -or
                $invalidNamespaces) {
                throw 'Expected asm.v1 assembly, manifestVersion 1.0 and one definition identity'
            }
            $identity = $identities[0]
            $record.name = $identity.GetAttribute('name')
            $record.architecture = $identity.GetAttribute('processorArchitecture')
            $record.token = $identity.GetAttribute('publicKeyToken')
            $record.type = $identity.GetAttribute('type')
            $record.version = $identity.GetAttribute('version')
            $null = Read-Vc90Version $record.version
            $familyName = if ($file.FullName -match '(?i)vc90\.(crt|openmp)_') { "Microsoft.VC90.$($Matches[1])" } else { throw 'Unexpected VC90 file prefix' }
            $expectedName = if ($isPolicy) { "policy.9.0.$familyName" } else { $familyName }
            $expectedType = if ($isPolicy) { 'win32-policy' } else { 'win32' }
            if ($record.name -ine $expectedName -or $record.architecture -ine 'amd64' -or
                $record.token -ine '1fc8b3b9a1e18e3b' -or $record.type -cne $expectedType -or
                $identity.SelectNodes('*').Count -or
                ($identity.HasAttribute('language') -and $identity.GetAttribute('language') -notin @('', '*'))) {
                throw 'Unexpected VC90 definition identity'
            }
            $children = @($root.SelectNodes('*'))
            $identityIndex = if (-not $isPolicy -and $children[0].LocalName -ceq 'noInheritable') { 1 } else { 0 }
            if ($children[$identityIndex] -ne $identity) { throw 'Definition identity must be first after optional noInheritable' }
            if ($isPolicy) {
                if ($root.SelectNodes('*[not(self::a:assemblyIdentity or self::a:dependency)]', $ns).Count) {
                    throw 'Unexpected publisher policy hierarchy'
                }
                foreach ($container in $root.SelectNodes('a:dependency', $ns)) {
                    $dependencies = $container.SelectNodes('a:dependentAssembly', $ns)
                    if (@($container.Attributes | Where-Object { $_.NamespaceURI -cne "http://www.w3.org/2000/xmlns/" }).Count -or $container.SelectNodes('*').Count -ne 1 -or $dependencies.Count -ne 1) {
                        throw 'Expected dependency/dependentAssembly hierarchy'
                    }
                    $dependent = $dependencies[0]
                    $dependencyIdentities = $dependent.SelectNodes('a:assemblyIdentity', $ns)
                    $redirects = $dependent.SelectNodes('a:bindingRedirect', $ns)
                    if (@($dependent.Attributes | Where-Object { $_.NamespaceURI -cne "http://www.w3.org/2000/xmlns/" }).Count -or $dependencyIdentities.Count -ne 1 -or $redirects.Count -lt 1 -or
                        $dependent.SelectNodes('*').Count -ne (1 + $redirects.Count) -or
                        $dependent.SelectNodes('*')[0] -ne $dependencyIdentities[0]) {
                        throw 'Expected one reference identity followed by redirects'
                    }
                    $dependency = $dependencyIdentities[0]
                    if ($dependency.GetAttribute('name') -ine $familyName -or
                        $dependency.GetAttribute('processorArchitecture') -ine $record.architecture -or
                        $dependency.GetAttribute('publicKeyToken') -ine $record.token -or
                        $dependency.GetAttribute('type') -cne 'win32' -or $dependency.HasAttribute('version') -or
                        $dependency.SelectNodes('*').Count -or
                        ($dependency.HasAttribute('language') -and $dependency.GetAttribute('language') -notin @('', '*'))) {
                        throw 'Policy reference identity does not match the definition'
                    }
                    foreach ($redirect in $redirects) {
                        $range = $redirect.GetAttribute('oldVersion').Split('-')
                        if ($range.Count -gt 2 -or $redirect.SelectNodes('*').Count) { throw 'Invalid redirect range or structure' }
                        $low = Read-Vc90Version $range[0]
                        $high = if ($range.Count -eq 2) { Read-Vc90Version $range[1] } else { $low }
                        $targetVersion = Read-Vc90Version $redirect.GetAttribute('newVersion')
                        if ($low -gt $high -or $low.Major -ne 9 -or $high.Major -ne 9 -or
                            $low.Minor -ne 0 -or $high.Minor -ne 0 -or $targetVersion.Major -ne 9 -or $targetVersion.Minor -ne 0) {
                            throw 'Invalid or mismatched VC90 redirect range'
                        }
                        foreach ($previous in $record.redirects) {
                            if ($low -le [version]$previous.high -and [version]$previous.low -le $high) {
                                throw 'Duplicate or overlapping redirect ranges in one policy'
                            }
                        }
                        $record.redirects += [ordered]@{ name = $dependency.GetAttribute('name'); architecture = $record.architecture
                            token = $record.token; type = 'win32'; old_version = $redirect.GetAttribute('oldVersion')
                            target_version = $redirect.GetAttribute('newVersion'); low = $low.ToString(); high = $high.ToString() }
                    }
                }
            }
            $record.valid = $true
        } catch {
            $record.error = [string]$_
            $errors += "$($file.FullName): $_"
        }
        $records += $record
    }
    # Separate installed policy versions are candidates, not a Windows policy-selection result.
    foreach ($policy in $records | Where-Object { $_.valid -and $_.type -ceq 'win32-policy' }) {
        $peers = @($records | Where-Object { $_.valid -and $_.name -ieq $policy.name -and [version]$_.version -eq [version]$policy.version })
        foreach ($left in $policy.redirects) {
            foreach ($right in @($peers | ForEach-Object { $_.redirects })) {
                if ([version]$left.low -le [version]$right.high -and [version]$right.low -le [version]$left.high -and
                    [version]$left.target_version -ne [version]$right.target_version) {
                    $errors += "Conflicting redirects for $($policy.name) policy version $($policy.version)"
                }
            }
        }
    }
    $compatible = @()
    foreach ($name in @('Microsoft.VC90.CRT', 'Microsoft.VC90.OpenMP')) {
        $matches = @()
        foreach ($policy in $records) {
            if (-not $policy.valid -or $policy.name -ine "policy.9.0.$name" -or $policy.architecture -ine 'amd64' -or
                $policy.token -ine '1fc8b3b9a1e18e3b' -or $policy.type -cne 'win32-policy') { continue }
            foreach ($redirect in $policy.redirects) {
                if ($redirect.name -ine $name -or $redirect.architecture -ine 'amd64' -or
                    $redirect.token -ine '1fc8b3b9a1e18e3b' -or $redirect.type -cne 'win32') { continue }
                $range = $redirect.old_version.Split('-')
                $low = [version]$range[0]
                $high = if ($range.Count -eq 2) { [version]$range[1] } else { $low }
                if ($range.Count -gt 2 -or [version]'9.0.21022.8' -lt $low -or [version]'9.0.21022.8' -gt $high) { continue }
                $targets = @($records | Where-Object { $_.valid -and $_.name -ieq $name -and $_.architecture -ieq 'amd64' -and
                    $_.token -ieq '1fc8b3b9a1e18e3b' -and $_.type -ceq 'win32' -and [version]$_.version -eq [version]$redirect.target_version -and
                    (Test-Path $_.assembly_directory -PathType Container) })
                foreach ($target in $targets) {
                    $matches += [ordered]@{ policy = $policy.source; old_version = $redirect.old_version
                        target_version = $redirect.target_version; target_manifest = $target.source; target_directory = $target.assembly_directory }
                }
            }
        }
        $compatible += [ordered]@{ name = $name; requested_version = '9.0.21022.8'; matches = $matches }
    }
    $evidence = [ordered]@{ discovery = $enumerations; assemblies = $records; compatibility = $compatible; errors = @($errors | Select-Object -Unique)
        status = $(if ($errors.Count -or @($compatible | Where-Object { $_.matches.Count -eq 0 }).Count) { 'UNPROVEN' } else { 'POLICY_AND_TARGET_PRESENT' })
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
            try { Get-Vc90MsiDestinationObservation -Destination $Destination } catch { $receipt.observation_error = [string]$_ }
            try { Get-Vc90PolicyEvidence -Destination $Destination } catch { $receipt.policy_error = [string]$_ }
            throw "VC2008 SP1 installer exit $($process.ExitCode): $($receipt.installer_result)" }
        try { Get-Vc90MsiDestinationObservation -Destination $Destination } catch { $receipt.observation_error = [string]$_ }
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
            try { Get-Vc90MsiDestinationObservation -Destination $Destination } catch { $receipt.observation_error = [string]$_ }
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
