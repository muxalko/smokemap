#Requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('\Afixture-[a-f0-9]{12}\z')][string]$RunId)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$moduleRoot = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $moduleRoot 'SmokemapBackupCrypto.psm1')
$receiver = Join-Path $moduleRoot 'Receive-SmokemapBackup.ps1'
$sandbox = Join-Path $PSScriptRoot ('.tmp-receiver-' + [guid]::NewGuid().ToString('N'))

try {
    $null = New-SmokemapBackupPrivateDirectory -OutputDirectory $sandbox
    $backups = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $sandbox 'backups')
    $receipts = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $sandbox 'receipts')
    $restored = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $sandbox 'restored')
    $key = New-SmokemapBackupRecipient -OutputDirectory (Join-Path $sandbox 'keys') -KeySize 3072
    $options = @{
        BackupRoot = $backups; ReceiptRoot = $receipts
        PublicKeyPath = $key.PublicKey; PrivateKeyPath = $key.PrivateKey
    }
    $null = & $receiver @options -Fixture -RunId $RunId
    $receiptPath = Join-Path $receipts ($RunId + '.json')
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $cipherRoot = Join-Path $backups $RunId
    if ($receipt.RunId -cne $RunId -or $receipt.Environment -cne 'fixture' -or $receipt.Envelopes.Count -ne 3 -or
        @(Get-ChildItem -LiteralPath $cipherRoot -Force | Where-Object Extension -cne '.smkbkp').Count) {
        throw 'Receipt or encrypted set did not match the fixture.'
    }
    $manifest = $receipt.Manifest
    $manifestPath = Join-Path $restored 'manifest.json'
    $null = Restore-SmokemapBackupEnvelope -InputPath (Join-Path $cipherRoot 'manifest.json.smkbkp') -OutputPath $manifestPath `
        -PrivateKeyPath $key.PrivateKey -ExpectedPlaintextLength $manifest.PlaintextBytes `
        -ExpectedPlaintextSha256 $manifest.PlaintextSha256 -BackupIdentity $manifest.Identity
    $export = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $export.files) {
        if ($entry.name -cnotin @('database.dump', 'media.tar')) { throw 'Unexpected restored manifest entry.' }
        $file = Join-Path $restored $entry.name
        $null = Restore-SmokemapBackupEnvelope -InputPath (Join-Path $cipherRoot ($entry.name + '.smkbkp')) -OutputPath $file `
            -PrivateKeyPath $key.PrivateKey -ExpectedPlaintextLength $entry.bytes -ExpectedPlaintextSha256 $entry.sha256 `
            -BackupIdentity ($RunId + '/' + $entry.name)
    }
    $corruptRun = $RunId + '-bad'
    $rejected = $false
    try { $null = & $receiver @options -Fixture -RunId $corruptRun }
    catch { $rejected = $_.Exception.Message.Contains('does not match its manifest') }
    if (-not $rejected -or (Test-Path -LiteralPath (Join-Path $backups $corruptRun)) -or
        (Test-Path -LiteralPath (Join-Path $receipts ($corruptRun + '.json'))) -or
        @(Get-ChildItem -LiteralPath $backups -Force -Filter '.incoming-*').Count) {
        throw 'Corrupt fixture was not rejected without publication or residual staging.'
    }
    $before = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash
    $rejected = $false
    try { $null = & $receiver @options -Fixture -RunId $RunId }
    catch { $rejected = $_.Exception.Message.Contains('already exists') }
    if (-not $rejected -or (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash -cne $before) {
        throw 'Existing receipt was not preserved.'
    }
    [pscustomobject]@{ Fixture = $RunId; RestoredFiles = 2; VerifiedEnvelopes = 3
        CorruptPairRejected = $true; DuplicateRejected = $true; LiveDataUsed = $false } | ConvertTo-Json -Compress
}
finally {
    $full = [IO.Path]::GetFullPath($sandbox)
    if ([IO.Path]::GetDirectoryName($full) -cne $PSScriptRoot -or
        [IO.Path]::GetFileName($full) -cnotmatch '\A\.tmp-receiver-[a-f0-9]{32}\z') {
        throw 'Refusing cleanup outside the exact disposable receiver directory.'
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
