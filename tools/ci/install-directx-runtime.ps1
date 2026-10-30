function Install-DirectXRuntime {
    param([Parameter(Mandatory)][string] $OutputDirectory)

    $ErrorActionPreference = 'Stop'
    New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
    $archive = Join-Path $OutputDirectory 'directx_Jun2010_redist.exe'
    $unpack = Join-Path $OutputDirectory 'unpacked'
    $metadata = [ordered]@{
        requested_url = 'https://download.microsoft.com/download/8/4/a/84a35bf1-dafe-4ae8-82af-ad2ae20b6b14/directx_Jun2010_redist.exe'
        status = $null
        final_url = $null
        headers = [ordered]@{}
        size = $null
        sha256 = $null
        first_bytes_hex = $null
        authenticode_status = $null
        body_observation_error = $null
        error = $null
    }
    try {
        # Keep the body of this single request, including HTTP error responses.
        try {
            $response = Invoke-WebRequest $metadata.requested_url -OutFile $archive -PassThru -SkipHttpErrorCheck
        } finally {
            try {
                if (Test-Path $archive) {
                    $metadata.size = (Get-Item $archive).Length
                    $metadata.sha256 = (Get-FileHash $archive -Algorithm SHA256).Hash
                    $stream = [System.IO.File]::OpenRead($archive)
                    try {
                        $prefix = [byte[]]::new(32)
                        $count = $stream.Read($prefix, 0, $prefix.Length)
                        $metadata.first_bytes_hex = [Convert]::ToHexString($prefix, 0, $count)
                    } finally {
                        $stream.Dispose()
                    }
                }
            } catch {
                $metadata.body_observation_error = $_.Exception.Message
            }
            if (Test-Path $archive) {
                try {
                    $metadata.authenticode_status = [string](Get-AuthenticodeSignature $archive).Status
                } catch {
                    $metadata.authenticode_status = 'ObservationUnavailable'
                }
            }
        }
        $metadata.status = [int]$response.StatusCode
        $metadata.final_url = $response.BaseResponse.RequestMessage.RequestUri.AbsoluteUri
        foreach ($name in @('Content-Type', 'Content-Length', 'Date', 'Server', 'ETag', 'Last-Modified')) {
            if ($response.Headers.ContainsKey($name)) {
                $metadata.headers[$name] = @($response.Headers[$name]) -join ', '
            }
        }
        if ($metadata.status -lt 200 -or $metadata.status -ge 300) {
            throw "DirectX download HTTP status: $($metadata.status)"
        }
        # Microsoft Download Center, id=8109. Keep the exact tested payload.
        if ($metadata.sha256 -ne '053F76DCBB28802E23341B6A787E3B0791C0FA5C8D4D011B1044172DBF89C73B') {
            throw 'Unexpected DirectX redistributable payload'
        }
        New-Item -ItemType Directory -Force $unpack | Out-Null
        $extract = Start-Process -FilePath $archive -ArgumentList '/Q', ('/T:"{0}"' -f $unpack) -Wait -PassThru -WindowStyle Hidden
        if ($extract.ExitCode -ne 0) { throw "DirectX extraction failed: $($extract.ExitCode)" }
        $install = Start-Process -FilePath (Join-Path $unpack 'DXSETUP.exe') -ArgumentList '/silent' -Wait -PassThru -WindowStyle Hidden
        if ($install.ExitCode -ne 0) { throw "DirectX installation failed: $($install.ExitCode)" }
    } catch {
        $metadata.error = $_.Exception.Message
        throw
    } finally {
        try {
            $metadata | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $OutputDirectory 'response.json') -Encoding utf8
        } catch {
            if ($null -eq $metadata.error) { throw }
            Write-Warning "Could not preserve DirectX metadata: $($_.Exception.Message)"
        }
    }
}
