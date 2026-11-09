#Requires -Version 7.4
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\SmokemapBackupCrypto.psm1') -Force

if (-not ('Smokemap.BackupTests.FragmentedStream' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.IO;
namespace Smokemap.BackupTests {
 public sealed class FragmentedStream : Stream {
  private readonly MemoryStream inner;
  private Action beforeRead;
  public FragmentedStream(byte[] bytes) { inner = new MemoryStream(bytes, false); }
  public FragmentedStream(byte[] bytes, Action beforeRead) : this(bytes) { this.beforeRead = beforeRead; }
  public override bool CanRead => true;
  public override bool CanSeek => false;
  public override bool CanWrite => false;
  public override long Length => throw new NotSupportedException();
  public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
  public override int Read(byte[] b, int offset, int count) {
   var callback = beforeRead;
   beforeRead = null;
   callback?.Invoke();
   return inner.Read(b, offset, Math.Min(count, 17));
  }
  public override int ReadByte() => inner.ReadByte();
  public override void Flush() { }
  public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
  public override void SetLength(long value) => throw new NotSupportedException();
  public override void Write(byte[] b, int offset, int count) => throw new NotSupportedException();
  protected override void Dispose(bool value) { if(value) inner.Dispose(); base.Dispose(value); }
 }
}
'@
}

$script:passed = 0
function Assert-True([bool]$Value, [string]$Label) {
    if (-not $Value) { throw "FAIL: $Label" }
}
function Pass([string]$Label) { $script:passed++; Write-Output "PASS $Label" }
function Sha([byte[]]$Bytes) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }
function Slice([byte[]]$Bytes, [int]$Offset, [int]$Count) {
    $result = [byte[]]::new($Count)
    [Array]::Copy($Bytes, $Offset, $result, 0, $Count)
    return ,$result
}

$testParent = [IO.Path]::GetFullPath($PSScriptRoot)
$testRoot = Join-Path $testParent ('.tmp-crypto-' + [guid]::NewGuid().ToString('N'))
$identity = 'test-20261108/database.dump'
$script:badCount = 0
$journal = [System.Collections.Generic.List[string]]::new()
try {
    $null = New-SmokemapBackupPrivateDirectory -OutputDirectory $testRoot
    $key = New-SmokemapBackupRecipient -OutputDirectory (Join-Path $testRoot 'disposable-keys') -KeySize 3072
    $otherKey = New-SmokemapBackupRecipient -OutputDirectory (Join-Path $testRoot 'disposable-wrong-keys') -KeySize 3072
    Pass 'disposable key generation and strict owner/SYSTEM ACLs'
    $beforeAcl = (Get-Acl $testRoot).Sddl
    $rejected = $false
    try { $null = New-SmokemapBackupPrivateDirectory -OutputDirectory $testRoot } catch { $rejected = $true }
    Assert-True ($rejected -and $beforeAcl -eq (Get-Acl $testRoot).Sddl) 'existing directory must not be altered'
    Pass 'existing key/output directory protection'

    $chunk = [Smokemap.BackupPrototype.Envelope]::ChunkSize
    foreach ($size in @(0, 1, ($chunk - 1), $chunk, ($chunk + 1), (2 * $chunk + 37))) {
        $bytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes($size)
        $plainHash = Sha $bytes
        $encrypted = Join-Path $testRoot "sample-$size.smkbkp"
        $restored = Join-Path $testRoot "sample-$size.restored"
        $stream = [Smokemap.BackupTests.FragmentedStream]::new($bytes)
        try {
            $receipt = Protect-SmokemapBackup -InputStream $stream -OutputPath $encrypted -PublicKeyPath $key.PublicKey -ExpectedPlaintextLength $size -BackupIdentity $identity
        } finally { $stream.Dispose() }
        Assert-True ($receipt.PlaintextSha256 -eq $plainHash -and $receipt.PlaintextBytes -eq $size) 'streamed encryption hash/size'
        Assert-True ($receipt.EnvelopeSha256 -eq (Get-FileHash -LiteralPath $encrypted -Algorithm SHA256).Hash.ToLowerInvariant()) 'ciphertext hash'
        $beforeFiles = @(Get-ChildItem -LiteralPath $testRoot -File).Count
        $verified = Test-SmokemapBackupEnvelope -InputPath $encrypted -PrivateKeyPath $key.PrivateKey -ExpectedPlaintextLength $size -ExpectedPlaintextSha256 $plainHash -BackupIdentity $identity
        Assert-True (@(Get-ChildItem -LiteralPath $testRoot -File).Count -eq $beforeFiles) 'verification must produce no plaintext file'
        Assert-True ($verified.EnvelopeSha256 -eq $receipt.EnvelopeSha256 -and $verified.PlaintextSha256 -eq $plainHash) 'verify receipt parity'
        $restoredReceipt = Restore-SmokemapBackupEnvelope -InputPath $encrypted -OutputPath $restored -PrivateKeyPath $key.PrivateKey -ExpectedPlaintextLength $size -ExpectedPlaintextSha256 $plainHash -BackupIdentity $identity
        Assert-True ((Get-FileHash -LiteralPath $restored -Algorithm SHA256).Hash.ToLowerInvariant() -eq $plainHash) 'restored content equality'
        $null = [Smokemap.BackupPrototype.SafeFiles]::CheckPrivateFile($restored)
        Pass "fragmented nonseekable stream roundtrip/verify/ACL size=$size"
    }

    $samplePath = Join-Path $testRoot "sample-$(2 * $chunk + 37).smkbkp"
    $valid = [IO.File]::ReadAllBytes($samplePath)
    $size = 2 * $chunk + 37
    $validHash = (Get-FileHash -LiteralPath (Join-Path $testRoot "sample-$size.restored") -Algorithm SHA256).Hash.ToLowerInvariant()
    $headerSize = 68 + $identity.Length + 384
    $recordSize = 4 + $chunk + 16

    function Reject([string]$Label, [byte[]]$Envelope, [string]$KeyPath = $key.PrivateKey, [string]$Hash = $validHash, [long]$Length = $size, [string]$Identity = $identity) {
        $script:badCount++
        $candidate = Join-Path $testRoot "bad-$script:badCount.smkbkp"
        $output = Join-Path $testRoot "bad-$script:badCount.output"
        [IO.File]::WriteAllBytes($candidate, $Envelope)
        $failed = $false
        try {
            $null = Restore-SmokemapBackupEnvelope -InputPath $candidate -OutputPath $output -PrivateKeyPath $KeyPath -ExpectedPlaintextLength $Length -ExpectedPlaintextSha256 $Hash -BackupIdentity $Identity
        } catch { $failed = $true }
        Assert-True $failed "$Label rejected"
        Assert-True (-not [IO.File]::Exists($output)) "$Label must not publish plaintext"
        Assert-True (@(Get-ChildItem -LiteralPath $testRoot -Force -Filter '.smkbkp-partial-*').Count -eq 0) "$Label must remove private partial output"
        Pass "reject $Label without plaintext publication or residual partial"
    }

    foreach ($case in @{
        magic = 0; algorithm = 8; reserved = 10; chunkSize = 15; length = 23;
        identityLength = 25; wrappedLength = 27; nonce = 28; fingerprint = 36;
        identity = 68; wrappedKey = (68 + $identity.Length); ciphertext = ($headerSize + 4);
        dataTag = ($headerSize + 4 + $chunk); finalTag = ($valid.Length - 1)
    }.GetEnumerator()) {
        $changed = [byte[]]$valid.Clone()
        $changed[$case.Value] = $changed[$case.Value] -bxor 1
        Reject -Label "tampered $($case.Key)" -Envelope $changed
    }
    foreach ($cut in @(0, 7, 67, ($headerSize - 1), ($headerSize + 3), ($valid.Length - 20), ($valid.Length - 1))) {
        Reject -Label "truncation at $cut" -Envelope (Slice $valid 0 $cut)
    }
    $trailing = [byte[]]::new($valid.Length + 1)
    [Array]::Copy($valid, $trailing, $valid.Length)
    Reject -Label 'trailing byte' -Envelope $trailing
    $reordered = [byte[]]$valid.Clone()
    [Array]::Copy($valid, $headerSize + $recordSize, $reordered, $headerSize, $recordSize)
    [Array]::Copy($valid, $headerSize, $reordered, $headerSize + $recordSize, $recordSize)
    Reject -Label 'reordered authenticated records' -Envelope $reordered
    $duplicated = [byte[]]$valid.Clone()
    [Array]::Copy($valid, $headerSize, $duplicated, $headerSize + $recordSize, $recordSize)
    Reject -Label 'duplicated authenticated record' -Envelope $duplicated
    $oversized = [byte[]]$valid.Clone()
    $oversized[$headerSize] = 127
    Reject -Label 'oversized record allocation' -Envelope $oversized
    Reject -Label 'wrong recipient' -Envelope $valid -KeyPath $otherKey.PrivateKey
    Reject -Label 'wrong trusted plaintext hash after all chunk tags pass' -Envelope $valid -Hash ('0' * 64)
    Reject -Label 'wrong trusted length' -Envelope $valid -Length ($size + 1)
    Reject -Label 'wrong trusted run/file identity' -Envelope $valid -Identity 'other-run/database.dump'

    foreach ($declared in @(36, 38)) {
        $source = [IO.MemoryStream]::new([byte[]](1..37))
        $destination = Join-Path $testRoot "wrong-declared-$declared.smkbkp"
        $failed = $false
        try { $null = Protect-SmokemapBackup -InputStream $source -OutputPath $destination -PublicKeyPath $key.PublicKey -ExpectedPlaintextLength $declared -BackupIdentity $identity } catch { $failed = $true } finally { $source.Dispose() }
        Assert-True ($failed -and -not [IO.File]::Exists($destination)) 'mismatched source length must not publish encrypted success'
        Assert-True (@(Get-ChildItem -LiteralPath $testRoot -Force -Filter '.smkbkp-partial-*').Count -eq 0) 'failed encryption partial cleanup'
        Pass "reject mismatched encryption source length declared=$declared"
    }

    $existing = Join-Path $testRoot 'keep-existing.txt'
    [IO.File]::WriteAllBytes($existing, [byte[]](1, 2, 3))
    $failed = $false
    try { $null = Restore-SmokemapBackupEnvelope -InputPath $samplePath -OutputPath $existing -PrivateKeyPath $key.PrivateKey -ExpectedPlaintextLength $size -ExpectedPlaintextSha256 $validHash -BackupIdentity $identity } catch { $failed = $true }
    Assert-True ($failed -and [Convert]::ToHexString([IO.File]::ReadAllBytes($existing)) -eq '010203') 'existing output must survive'
    Pass 'output collision refuses overwrite'

    $directoryInfo = [IO.DirectoryInfo]::new($testRoot)
    $acl = [IO.FileSystemAclExtensions]::GetAccessControl($directoryInfo, [Security.AccessControl.AccessControlSections]::Access)
    $wideAcl = [IO.FileSystemAclExtensions]::GetAccessControl($directoryInfo, [Security.AccessControl.AccessControlSections]::Access)
    $everyone = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
    $wideAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($everyone, [Security.AccessControl.FileSystemRights]::Read, [Security.AccessControl.AccessControlType]::Allow))
    [IO.FileSystemAclExtensions]::SetAccessControl($directoryInfo, $wideAcl)
    $failed = $false
    try { $null = [Smokemap.BackupPrototype.SafeFiles]::CheckPrivateDirectory($testRoot) } catch { $failed = $true } finally { [IO.FileSystemAclExtensions]::SetAccessControl($directoryInfo, $acl) }
    Assert-True $failed 'broadened ACL must be refused'
    Pass 'ACL broadening rejected'

    # Read-only check of a Windows compatibility alias. Creating links is not
    # needed, and may be prohibited by the agent's filesystem boundary.
    $junction = Join-Path $env:SystemDrive 'Users\All Users'
    Assert-True (([IO.File]::GetAttributes($junction) -band [IO.FileAttributes]::ReparsePoint) -ne 0) 'Windows reparse fixture must really be a link'
    $failed = $false
    try { $null = [Smokemap.BackupPrototype.SafeFiles]::NoLinks($junction) } catch { $failed = $_.Exception.Message.Contains('Reparse points are forbidden') }
    Assert-True $failed 'junction must be rejected'
    Pass 'existing Windows reparse alias rejected using a read-only check'

    $linkTarget = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $testRoot 'link-target')
    $dangling = Join-Path $testRoot 'dangling-junction'
    New-Item -ItemType Junction -Path $dangling -Target $linkTarget | Out-Null
    try {
        [IO.Directory]::Delete($linkTarget)
        $failed = $false
        try { $null = [Smokemap.BackupPrototype.SafeFiles]::NoLinks($dangling) } catch { $failed = $_.Exception.Message.Contains('Reparse points are forbidden') }
        Assert-True $failed 'dangling junction must be rejected by the no-follow open'
        Pass 'dangling junction rejected'
    } finally {
        [IO.Directory]::Delete($dangling)
    }

    $ancestor = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $testRoot 'ancestor')
    $publication = New-SmokemapBackupPrivateDirectory -OutputDirectory (Join-Path $ancestor 'publication')
    $movedAncestor = Join-Path $testRoot 'renamed-ancestor'
    $race = @{ Attempted = $false; Blocked = $false }
    $stream = [Smokemap.BackupTests.FragmentedStream]::new([byte[]]@(42), [Action]{
        $race.Attempted = $true
        try { [IO.Directory]::Move($ancestor, $movedAncestor) } catch [IO.IOException] { $race.Blocked = $true }
    })
    try {
        $destination = Join-Path $publication 'race.smkbkp'
        $null = Protect-SmokemapBackup -InputStream $stream -OutputPath $destination -PublicKeyPath $key.PublicKey -ExpectedPlaintextLength 1 -BackupIdentity $identity
    } finally { $stream.Dispose() }
    Assert-True ($race.Attempted -and $race.Blocked -and [IO.File]::Exists($destination)) 'ancestor substitution must be blocked during publication'
    [IO.Directory]::Move($ancestor, $movedAncestor)
    Pass 'ancestor cannot be renamed during publication and is released afterwards'

    $ads = $samplePath + ':unexpected'
    $failed = $false
    try { $null = [Smokemap.BackupPrototype.SafeFiles]::OpenPrivateRead($ads) } catch { $failed = $_.Exception.Message.Contains('absolute local path') }
    Assert-True $failed 'alternate streams must be rejected before opening'
    Pass 'alternate data stream path rejected'

    $summary = [pscustomobject]@{ Passed = $script:passed; RejectionCases = $script:badCount; ProductionKeysCreated = $false; ActualBackupsCreated = $false; PlaintextPrinted = $false }
    $summary | ConvertTo-Json -Compress
}
finally {
    # Test artifacts only. Verify the absolute target is the newly generated test subtree.
    $full = [IO.Path]::GetFullPath($testRoot)
    if (-not $full.StartsWith($testParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($full) -notmatch '^\.tmp-crypto-[0-9a-f]{32}$') {
        throw 'Refusing cleanup outside the exact disposable test directory.'
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
