#Requires -Version 7.4
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not ('Smokemap.BackupPrototype.Envelope' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'BackupEnvelope.cs') -ErrorAction Stop
}

function New-SmokemapBackupPrivateDirectory {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string]$OutputDirectory)
    if ($PSCmdlet.ShouldProcess($OutputDirectory, 'Create a new owner/SYSTEM-only backup directory')) {
        [Smokemap.BackupPrototype.SafeFiles]::CreatePrivateDirectory($OutputDirectory)
    }
}

function New-SmokemapBackupRecipient {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$OutputDirectory,
        [ValidateRange(3072, 8192)][int]$KeySize = 4096
    )
    if ($PSCmdlet.ShouldProcess($OutputDirectory, 'Create a new private RSA backup recipient; refuse existing directory')) {
        $fingerprint = [Smokemap.BackupPrototype.SafeFiles]::GenerateRecipient($OutputDirectory, $KeySize)
        [pscustomobject]@{
            PublicKey = Join-Path $OutputDirectory 'recipient-public.spki'
            PrivateKey = Join-Path $OutputDirectory 'recipient-private.pk8'
            RecipientSha256 = $fingerprint
            KeySize = $KeySize
        }
    }
}

function Protect-SmokemapBackup {
    [CmdletBinding(DefaultParameterSetName = 'File')]
    param(
        [Parameter(Mandatory, ParameterSetName = 'File')][string]$InputPath,
        [Parameter(Mandatory, ParameterSetName = 'Stream')][System.IO.Stream]$InputStream,
        [Parameter(Mandatory)][string]$OutputPath,
        [Parameter(Mandatory)][string]$PublicKeyPath,
        [Parameter(Mandatory)][long]$ExpectedPlaintextLength,
        [Parameter(Mandatory)][string]$BackupIdentity
    )
    $recipient = $null
    $ownedInput = $null
    try {
        $recipient = [Smokemap.BackupPrototype.SafeFiles]::LoadRecipient($PublicKeyPath, $false)
        if ($PSCmdlet.ParameterSetName -eq 'File') {
            $ownedInput = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($InputPath)
            $InputStream = $ownedInput
        }
        [Smokemap.BackupPrototype.Envelope]::EncryptFile($InputStream, $OutputPath, $recipient, $ExpectedPlaintextLength, $BackupIdentity)
    }
    finally {
        if ($null -ne $ownedInput) { $ownedInput.Dispose() }
        if ($null -ne $recipient) { $recipient.Dispose() }
    }
}

function Test-SmokemapBackupEnvelope {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$InputPath,
        [Parameter(Mandatory)][string]$PrivateKeyPath,
        [Parameter(Mandatory)][long]$ExpectedPlaintextLength,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPlaintextSha256,
        [Parameter(Mandatory)][string]$BackupIdentity
    )
    $recipient = $null
    $input = $null
    try {
        $recipient = [Smokemap.BackupPrototype.SafeFiles]::LoadRecipient($PrivateKeyPath, $true)
        $input = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($InputPath)
        [Smokemap.BackupPrototype.Envelope]::Verify($input, $recipient, $ExpectedPlaintextLength, $BackupIdentity, $ExpectedPlaintextSha256)
    }
    finally {
        if ($null -ne $input) { $input.Dispose() }
        if ($null -ne $recipient) { $recipient.Dispose() }
    }
}

function Restore-SmokemapBackupEnvelope {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$InputPath,
        [Parameter(Mandatory)][string]$OutputPath,
        [Parameter(Mandatory)][string]$PrivateKeyPath,
        [Parameter(Mandatory)][long]$ExpectedPlaintextLength,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPlaintextSha256,
        [Parameter(Mandatory)][string]$BackupIdentity
    )
    $recipient = $null
    $input = $null
    try {
        $recipient = [Smokemap.BackupPrototype.SafeFiles]::LoadRecipient($PrivateKeyPath, $true)
        $input = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($InputPath)
        [Smokemap.BackupPrototype.Envelope]::RestoreFile($input, $OutputPath, $recipient, $ExpectedPlaintextLength, $BackupIdentity, $ExpectedPlaintextSha256)
    }
    finally {
        if ($null -ne $input) { $input.Dispose() }
        if ($null -ne $recipient) { $recipient.Dispose() }
    }
}

Export-ModuleMember -Function New-SmokemapBackupPrivateDirectory, New-SmokemapBackupRecipient, Protect-SmokemapBackup, Test-SmokemapBackupEnvelope, Restore-SmokemapBackupEnvelope
