#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('\A[a-z0-9][a-z0-9-]{7,63}\z')][string]$RunId,
    [Parameter(Mandatory)][string]$BackupRoot,
    [Parameter(Mandatory)][string]$ReceiptRoot,
    [Parameter(Mandatory)][string]$PublicKeyPath,
    [Parameter(Mandatory)][string]$PrivateKeyPath,
    [switch]$Fixture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SmokemapBackupCrypto.psm1') -ErrorAction Stop

$remoteRoot = '/home/michael/.local/state/smokemap-offvm-export'
$sshPath = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$manifestName = 'manifest.json'
$payloadNames = @('database.dump', 'media.tar')
$maxManifest = 65536
$maxPair = 16GB
$reserve = 10GB

function Receive-File([string]$Name, [string]$Destination, [long]$Limit) {
    if ($Name -cnotin @($manifestName, $payloadNames[0], $payloadNames[1])) { throw 'Unexpected export file name.' }
    $start = [Diagnostics.ProcessStartInfo]::new($sshPath)
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in @('-T', '-S', 'none', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no', '-o', 'ConnectTimeout=10',
            'michael@192.168.56.5', "cat -- $remoteRoot/$RunId/$Name")) {
        $start.ArgumentList.Add($argument)
    }

    $destinationStream = [IO.FileStream]::new($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $process = $null
    $deadline = [Threading.CancellationTokenSource]::new([TimeSpan]::FromMinutes(15))
    try {
        $process = [Diagnostics.Process]::Start($start)
        $stderr = $process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null, $deadline.Token)
        $stream = $process.StandardOutput.BaseStream
        $buffer = [byte[]]::new(1MB)
        $total = 0L
        while ($true) {
            $length = $stream.ReadAsync($buffer, 0, $buffer.Length, $deadline.Token).GetAwaiter().GetResult()
            if ($length -eq 0) { break }
            if ($length -gt ($Limit - $total)) { throw 'Export file exceeded its byte limit.' }
            $destinationStream.Write($buffer, 0, $length)
            $total += $length
        }
        $null = $process.WaitForExitAsync($deadline.Token).GetAwaiter().GetResult()
        $null = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw 'Authenticated Jenkins export transfer failed.' }
        $destinationStream.Flush($true)
        return $total
    }
    finally {
        if ($null -ne $process) {
            if (-not $process.HasExited) { $process.Kill($true); $process.WaitForExit() }
            $process.Dispose()
        }
        $deadline.Dispose()
        $destinationStream.Dispose()
    }
}

function Assert-Fields([Text.Json.JsonElement]$Object, [string[]]$Fields) {
    if ($Object.ValueKind -ne [Text.Json.JsonValueKind]::Object) { throw 'Expected a manifest object.' }
    $actual = @($Object.EnumerateObject() | ForEach-Object Name)
    if ($actual.Count -ne $Fields.Count -or @($Fields | Where-Object { $_ -cnotin $actual }).Count) {
        throw 'Manifest contains duplicate, missing or unknown fields.'
    }
}

function Read-Export([string]$Path) {
    $inputFile = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($Path)
    try {
        $document = [Text.Json.JsonDocument]::Parse($inputFile)
        try {
            $root = $document.RootElement
            Assert-Fields $root @('schema', 'run_id', 'environment', 'files')
            $environment = if ($Fixture) { 'fixture' } else { 'development' }
            if ($root.GetProperty('schema').GetInt32() -ne 1 -or
                $root.GetProperty('run_id').GetString() -cne $RunId -or
                $root.GetProperty('environment').GetString() -cne $environment) {
                throw 'Export schema, run ID or environment mismatch.'
            }
            $files = $root.GetProperty('files')
            if ($files.GetArrayLength() -ne $payloadNames.Count) { throw 'Export must contain a database/media pair.' }
            for ($index = 0; $index -lt $payloadNames.Count; $index++) {
                $item = $files[$index]
                Assert-Fields $item @('name', 'bytes', 'sha256')
                $name = $item.GetProperty('name').GetString()
                $size = $item.GetProperty('bytes').GetInt64()
                $hash = $item.GetProperty('sha256').GetString()
                if ($name -cne $payloadNames[$index] -or $size -lt 1 -or $size -gt $maxPair -or
                    $hash -cnotmatch '\A[0-9a-f]{64}\z') { throw 'Invalid export file identity, length or digest.' }
                [pscustomobject]@{ Name = $name; Bytes = $size; Sha256 = $hash }
            }
        } finally { $document.Dispose() }
    } finally { $inputFile.Dispose() }
}

function Get-PrivateHash([string]$Path) {
    $stream = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($Path)
    try { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
    finally { $stream.Dispose() }
}

function Write-Receipt([string]$Path, [object]$Receipt) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Receipt | ConvertTo-Json -Depth 5 -Compress))
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}

$backupPin = [Smokemap.BackupPrototype.SafeFiles]::HoldPrivateDirectory($BackupRoot)
try {
    $receiptPin = [Smokemap.BackupPrototype.SafeFiles]::HoldPrivateDirectory($ReceiptRoot)
    try {
        if ($BackupRoot.Equals($ReceiptRoot, [StringComparison]::OrdinalIgnoreCase) -or
            $ReceiptRoot.StartsWith($BackupRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $BackupRoot.StartsWith($ReceiptRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Backup and trusted receipt roots must be separate.'
        }
        $final = Join-Path $BackupRoot $RunId
        $rootReceipt = Join-Path $ReceiptRoot ($RunId + '.json')
        foreach ($path in @($final, $rootReceipt)) {
            $null = [Smokemap.BackupPrototype.SafeFiles]::NoLinks($path)
            if ([IO.File]::Exists($path) -or [IO.Directory]::Exists($path)) { throw 'A completed or partial backup with this run ID already exists.' }
        }
        $stage = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $BackupRoot ('.incoming-' + $RunId))
        $temporaryReceipt = Join-Path $ReceiptRoot ('.incoming-' + $RunId + '-' + [guid]::NewGuid().ToString('N'))
        try {
            $manifest = Join-Path $stage $manifestName
            $manifestBytes = Receive-File $manifestName $manifest $maxManifest
            $manifestDigest = Get-PrivateHash $manifest
            $entries = @(Read-Export $manifest)
            $total = $entries[0].Bytes + $entries[1].Bytes
            if ($total -gt $maxPair -or [IO.DriveInfo]::new([IO.Path]::GetPathRoot($BackupRoot)).AvailableFreeSpace -lt ($reserve + 2 * $total)) {
                throw 'Backup exceeds the configured byte or free-space budget.'
            }
            foreach ($entry in $entries) {
                $path = Join-Path $stage $entry.Name
                if ((Receive-File $entry.Name $path $entry.Bytes) -ne $entry.Bytes -or (Get-PrivateHash $path) -cne $entry.Sha256) {
                    throw 'Transferred payload does not match its manifest.'
                }
            }
            $entries += [pscustomobject]@{ Name = $manifestName; Bytes = $manifestBytes; Sha256 = $manifestDigest }
            $verifiedFiles = foreach ($entry in $entries) {
                $plain = Join-Path $stage $entry.Name
                $cipher = $plain + '.smkbkp'
                $identity = $RunId + '/' + $entry.Name
                $written = Protect-SmokemapBackup -InputPath $plain -OutputPath $cipher -PublicKeyPath $PublicKeyPath -ExpectedPlaintextLength $entry.Bytes -BackupIdentity $identity
                $verified = Test-SmokemapBackupEnvelope -InputPath $cipher -PrivateKeyPath $PrivateKeyPath -ExpectedPlaintextLength $entry.Bytes -ExpectedPlaintextSha256 $entry.Sha256 -BackupIdentity $identity
                if ($verified.EnvelopeSha256 -cne $written.EnvelopeSha256) { throw 'Encrypted output changed after publication.' }
                [IO.File]::Delete($plain)
                [pscustomobject]@{ Name = $entry.Name; Identity = $identity; PlaintextBytes = $verified.PlaintextBytes
                    PlaintextSha256 = $verified.PlaintextSha256; EnvelopeBytes = $verified.EnvelopeBytes
                    EnvelopeSha256 = $verified.EnvelopeSha256; RecipientSha256 = $verified.RecipientSha256 }
            }
            $receipt = [pscustomobject]@{
                Schema = 1; RunId = $RunId; Environment = $(if ($Fixture) { 'fixture' } else { 'development' })
                VerifiedAtUtc = [DateTimeOffset]::UtcNow.ToString('o')
                Manifest = $verifiedFiles | Where-Object Name -ceq $manifestName
                Envelopes = @($verifiedFiles | Select-Object Name, EnvelopeBytes, EnvelopeSha256)
            }
            Write-Receipt $temporaryReceipt $receipt
            [IO.Directory]::Move($stage, $final)
            # Readers require this separate root receipt. A failed second rename leaves an
            # encrypted orphan for reconciliation and does not claim a successful backup.
            [IO.File]::Move($temporaryReceipt, $rootReceipt, $false)
            $receipt
        }
        finally {
            if ([IO.Directory]::Exists($stage)) {
                foreach ($name in @($manifestName) + $payloadNames) {
                    [IO.File]::Delete((Join-Path $stage $name))
                    [IO.File]::Delete((Join-Path $stage ($name + '.smkbkp')))
                }
                [IO.Directory]::Delete($stage)
            }
            [IO.File]::Delete($temporaryReceipt)
        }
    } finally { $receiptPin.Dispose() }
} finally { $backupPin.Dispose() }
