$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/install-directx-runtime.ps1"

$expectedHash = '053F76DCBB28802E23341B6A787E3B0791C0FA5C8D4D011B1044172DBF89C73B'
$fixture = [System.Text.Encoding]::UTF8.GetBytes('inert DirectX response fixture')
$fixtureHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($fixture))

function Assert($condition, [string] $message) {
    if (-not $condition) { throw $message }
}

function Invoke-WebRequest {
    param($Uri, $OutFile, [switch] $PassThru, [switch] $SkipHttpErrorCheck)
    $script:requests++
    Assert ($PassThru -and $SkipHttpErrorCheck) 'Response and error-body capture required'
    [System.IO.File]::WriteAllBytes($OutFile, $fixture)
    if ($script:transportFailure) { throw 'fixture transport failure' }
    return [pscustomobject]@{
        StatusCode = $script:status
        BaseResponse = [pscustomobject]@{
            RequestMessage = [pscustomobject]@{ RequestUri = [uri]'https://example.invalid/final' }
        }
        Headers = @{
            'Content-Type' = 'application/octet-stream'
            'Set-Cookie' = 'must not be retained'
            'X-Unknown' = 'must not be retained'
        }
    }
}

function Get-FileHash {
    param($Path, $Algorithm)
    if ($script:acceptedFixture) { return [pscustomobject]@{ Hash = $expectedHash } }
    Microsoft.PowerShell.Utility\Get-FileHash $Path -Algorithm $Algorithm
}

function Get-AuthenticodeSignature {
    param($FilePath)
    if ($script:metadataWriteFailure -and $script:transportFailure) {
        return [pscustomobject]@{ Status = 'NotSigned' }
    }
    throw 'fixture signature unavailable'
}

function Set-Content {
    param($Path, $Encoding, [Parameter(ValueFromPipeline)] $Value)
    process {
        if ($script:metadataWriteFailure) {
            $script:attemptedMetadata = $Value | ConvertFrom-Json
            throw 'fixture metadata write failure'
        }
        Microsoft.PowerShell.Management\Set-Content -Path $Path -Encoding $Encoding -Value $Value
    }
}

function Start-Process {
    param($FilePath, $ArgumentList, [switch] $Wait, [switch] $PassThru, $WindowStyle)
    $script:processes += $FilePath
    $code = if ($script:processes.Count -eq 1) { $script:extractExit } else { $script:installExit }
    return [pscustomobject]@{ ExitCode = $code }
}

$root = Join-Path $env:RUNNER_TEMP ('directx-fixtures-' + [guid]::NewGuid())
foreach ($case in @('http-error', 'hash-mismatch', 'success', 'extraction-error', 'installation-error', 'transport-error', 'metadata-write-success', 'metadata-write-http-error', 'metadata-write-transport-error')) {
    $script:requests = 0
    $script:processes = @()
    $script:status = if ($case -in @('http-error', 'metadata-write-http-error')) { 503 } else { 200 }
    $script:acceptedFixture = $case -in @('http-error', 'success', 'extraction-error', 'installation-error', 'metadata-write-success', 'metadata-write-http-error')
    $script:transportFailure = $case -in @('transport-error', 'metadata-write-transport-error')
    $script:metadataWriteFailure = $case -like 'metadata-write-*'
    $script:attemptedMetadata = $null
    $script:extractExit = if ($case -eq 'extraction-error') { 7 } else { 0 }
    $script:installExit = if ($case -eq 'installation-error') { 9 } else { 0 }
    $output = Join-Path $root $case
    $failure = $null
    try { Install-DirectXRuntime -OutputDirectory $output } catch { $failure = $_.Exception.Message }
    Assert ($script:requests -eq 1) "$case must make exactly one request"
    Assert (($null -eq $failure) -eq ($case -eq 'success')) "$case failure state"
    if ($script:metadataWriteFailure) {
        Assert (-not (Test-Path (Join-Path $output 'response.json'))) "$case metadata write failed"
        $metadata = $script:attemptedMetadata
    } else {
        $metadata = Get-Content (Join-Path $output 'response.json') -Raw | ConvertFrom-Json
    }
    if ($case -eq 'metadata-write-success') {
        Assert ($null -eq $metadata.error) "$case no primary failure"
    } else {
        Assert ($metadata.error -eq $failure) "$case original failure retained"
    }
    $body = [System.IO.File]::ReadAllBytes((Join-Path $output 'directx_Jun2010_redist.exe'))
    Assert ([Convert]::ToHexString($body) -eq [Convert]::ToHexString($fixture)) "$case body retained"
    Assert ($metadata.size -eq $fixture.Length) "$case byte size retained"
    $hash = if ($script:acceptedFixture) { $expectedHash } else { $fixtureHash }
    Assert ($metadata.sha256 -eq $hash) "$case hash retained"
    Assert ($metadata.first_bytes_hex -eq [Convert]::ToHexString($fixture)) "$case first bytes retained"
    Assert ($metadata.headers.PSObject.Properties.Name -notcontains 'Set-Cookie') "$case cookie excluded"
    Assert ($metadata.headers.PSObject.Properties.Name -notcontains 'X-Unknown') "$case unknown header excluded"
    $signature = if ($script:metadataWriteFailure -and $script:transportFailure) { 'NotSigned' } else { 'ObservationUnavailable' }
    Assert ($metadata.authenticode_status -eq $signature) "$case signature observation retained"
    if (-not $script:transportFailure) {
        Assert ($metadata.status -eq $script:status) "$case observed status retained"
        Assert ($metadata.final_url -eq 'https://example.invalid/final') "$case observed final URL retained"
    }
    $calls = switch ($case) {
        'extraction-error' { 1 }
        { $_ -in 'success', 'installation-error', 'metadata-write-success' } { 2 }
        default { 0 }
    }
    Assert ($script:processes.Count -eq $calls) "$case extraction/installation boundary"
    switch ($case) {
        'http-error' { Assert ($failure -like '*HTTP status: 503*') 'HTTP check precedes hash guard' }
        'hash-mismatch' { Assert ($failure -eq 'Unexpected DirectX redistributable payload') 'Fixed hash guard' }
        'extraction-error' { Assert ($failure -eq 'DirectX extraction failed: 7') 'Extraction exit check' }
        'installation-error' { Assert ($failure -eq 'DirectX installation failed: 9') 'Installation exit check' }
        'transport-error' { Assert ($failure -eq 'fixture transport failure') 'Original transport failure' }
        'metadata-write-success' { Assert ($failure -eq 'fixture metadata write failure') 'Metadata write failure fails success' }
        'metadata-write-http-error' { Assert ($failure -like '*HTTP status: 503*') 'Metadata write failure preserves HTTP failure' }
        'metadata-write-transport-error' { Assert ($failure -eq 'fixture transport failure') 'Metadata write failure preserves transport failure' }
    }
    Write-Host "PASS $case"
}
