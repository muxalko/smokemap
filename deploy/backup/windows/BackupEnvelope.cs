using System;
using System.IO;
using System.Text;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Smokemap.BackupPrototype
{
    public sealed class Receipt
    {
        public string Format { get; set; } = "SMKBKP01";
        public string Identity { get; set; }
        public string RecipientSha256 { get; set; }
        public long PlaintextBytes { get; set; }
        public long EnvelopeBytes { get; set; }
        public string PlaintextSha256 { get; set; }
        public string EnvelopeSha256 { get; set; }
        public uint DataRecords { get; set; }
    }

    // Prototype only. Operational orchestration and independent review are separate gates.
    public static class Envelope
    {
        public const int ChunkSize = 1048576;
        private const int TagSize = 16;
        private const int FixedHeaderSize = 68;
        private static readonly byte[] Magic = Encoding.ASCII.GetBytes("SMKBKP01");

        private static void Require(bool value, string message)
        {
            if (!value) throw new InvalidDataException(message);
        }

        private static byte[] IdentityBytes(string identity)
        {
            Require(identity != null && identity.Length >= 1 && identity.Length <= 256,
                "Backup identity must contain 1..256 ASCII characters.");
            foreach (char c in identity)
                Require((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                    (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-' || c == '/',
                    "Unsupported backup identity character.");
            return Encoding.ASCII.GetBytes(identity);
        }

        private static void CheckKey(RSA key)
        {
            if (key == null) throw new ArgumentNullException(nameof(key));
            Require(key.KeySize >= 3072 && key.KeySize <= 8192 && key.KeySize % 8 == 0,
                "RSA recipient must contain 3072..8192 bits.");
            Require(AesGcm.IsSupported, "AES-GCM is unavailable.");
        }

        private static string Hex(byte[] bytes) => Convert.ToHexString(bytes).ToLowerInvariant();

        private static byte[] ExpectedHash(string text)
        {
            Require(text != null && text.Length == 64, "Expected SHA256 is required.");
            try { return Convert.FromHexString(text); }
            catch (FormatException) { throw new InvalidDataException("Expected SHA256 is invalid."); }
        }

        private static byte[] Nonce(byte[] prefix, uint index)
        {
            var nonce = new byte[12];
            prefix.CopyTo(nonce, 0);
            BinaryPrimitives.WriteUInt32BigEndian(nonce.AsSpan(8), index);
            return nonce;
        }

        private static byte[] Aad(byte[] headerHash, uint index, uint length)
        {
            var result = new byte[40];
            headerHash.CopyTo(result, 0);
            BinaryPrimitives.WriteUInt32BigEndian(result.AsSpan(32), index);
            BinaryPrimitives.WriteUInt32BigEndian(result.AsSpan(36), length);
            return result;
        }

        private static void Write(Stream output, byte[] bytes, int count, IncrementalHash hash, ref long size)
        {
            output.Write(bytes, 0, count);
            hash.AppendData(bytes, 0, count);
            size = checked(size + count);
        }

        private static byte[] Read(Stream input, int size, IncrementalHash hash, ref long total)
        {
            var result = new byte[size];
            int offset = 0;
            while (offset < size)
            {
                int count = input.Read(result, offset, size - offset);
                if (count == 0) throw new EndOfStreamException("Incomplete backup envelope.");
                offset += count;
            }
            hash.AppendData(result);
            total = checked(total + size);
            return result;
        }

        private static byte[] Header(RSA key, long length, string identity, byte[] prefix, byte[] wrapped)
        {
            byte[] context = IdentityBytes(identity);
            var header = new byte[FixedHeaderSize + context.Length + wrapped.Length];
            Magic.CopyTo(header, 0);
            header[8] = 1; // RSA-OAEP-SHA256
            header[9] = 1; // AES-256-GCM, 16-byte tag
            // Bytes 10..11 are reserved zero.
            BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(12), ChunkSize);
            BinaryPrimitives.WriteInt64BigEndian(header.AsSpan(16), length);
            BinaryPrimitives.WriteUInt16BigEndian(header.AsSpan(24), checked((ushort)context.Length));
            BinaryPrimitives.WriteUInt16BigEndian(header.AsSpan(26), checked((ushort)wrapped.Length));
            prefix.CopyTo(header, 28);
            SHA256.HashData(key.ExportSubjectPublicKeyInfo()).CopyTo(header, 36);
            context.CopyTo(header, FixedHeaderSize);
            wrapped.CopyTo(header, FixedHeaderSize + context.Length);
            return header;
        }

        private static void CheckLength(long length)
        {
            // uint.MaxValue data chunks maximum; the final marker uses the remaining index.
            Require(length >= 0 && (ulong)length <= (ulong)uint.MaxValue * ChunkSize,
                "Plaintext length exceeds the format bound.");
        }

        public static Receipt Encrypt(Stream input, Stream output, RSA recipient, long expectedLength, string identity)
        {
            CheckKey(recipient);
            CheckLength(expectedLength);
            IdentityBytes(identity);
            if (input == null || output == null || !input.CanRead || !output.CanWrite)
                throw new ArgumentException("Readable input and writable output required.");
            byte[] contentKey = RandomNumberGenerator.GetBytes(32);
            byte[] plain = new byte[ChunkSize];
            byte[] cipher = new byte[ChunkSize];
            try
            {
                byte[] prefix = RandomNumberGenerator.GetBytes(8);
                byte[] wrapped = recipient.Encrypt(contentKey, RSAEncryptionPadding.OaepSHA256);
                byte[] header = Header(recipient, expectedLength, identity, prefix, wrapped);
                byte[] headerHash = SHA256.HashData(header);
                using var cipherHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                using var plainHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                using var aes = new AesGcm(contentKey, TagSize);
                long envelopeBytes = 0, done = 0;
                uint index = 0;
                Write(output, header, header.Length, cipherHash, ref envelopeBytes);
                while (done < expectedLength)
                {
                    Require(index < uint.MaxValue, "Chunk counter exhausted.");
                    int size = (int)Math.Min(ChunkSize, expectedLength - done);
                    int offset = 0;
                    while (offset < size)
                    {
                        int count = input.Read(plain, offset, size - offset);
                        if (count == 0) throw new EndOfStreamException("Input is shorter than its manifest.");
                        offset += count;
                    }
                    var tag = new byte[TagSize];
                    aes.Encrypt(Nonce(prefix, index), plain.AsSpan(0, size), cipher.AsSpan(0, size), tag,
                        Aad(headerHash, index, (uint)size));
                    var sizeBytes = new byte[4];
                    BinaryPrimitives.WriteUInt32BigEndian(sizeBytes, (uint)size);
                    Write(output, sizeBytes, 4, cipherHash, ref envelopeBytes);
                    Write(output, cipher, size, cipherHash, ref envelopeBytes);
                    Write(output, tag, TagSize, cipherHash, ref envelopeBytes);
                    plainHash.AppendData(plain, 0, size);
                    CryptographicOperations.ZeroMemory(plain.AsSpan(0, size));
                    done = checked(done + size);
                    index++;
                }
                Require(input.ReadByte() == -1, "Input is longer than its manifest.");
                var finalTag = new byte[TagSize];
                aes.Encrypt(Nonce(prefix, index), Array.Empty<byte>(), Array.Empty<byte>(), finalTag,
                    Aad(headerHash, index, 0));
                Write(output, new byte[4], 4, cipherHash, ref envelopeBytes);
                Write(output, finalTag, TagSize, cipherHash, ref envelopeBytes);
                return new Receipt {
                    Identity = identity, RecipientSha256 = Hex(SHA256.HashData(recipient.ExportSubjectPublicKeyInfo())),
                    PlaintextBytes = done, EnvelopeBytes = envelopeBytes, PlaintextSha256 = Hex(plainHash.GetHashAndReset()),
                    EnvelopeSha256 = Hex(cipherHash.GetHashAndReset()), DataRecords = index
                };
            }
            finally
            {
                CryptographicOperations.ZeroMemory(contentKey);
                CryptographicOperations.ZeroMemory(plain);
                CryptographicOperations.ZeroMemory(cipher);
            }
        }

        private static Receipt Decrypt(Stream input, Stream output, RSA recipient, long expectedLength,
            string expectedIdentity, string expectedPlaintextSha256)
        {
            CheckKey(recipient);
            CheckLength(expectedLength);
            byte[] expectedIdentityBytes = IdentityBytes(expectedIdentity);
            byte[] expectedHash = ExpectedHash(expectedPlaintextSha256);
            using var cipherHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            using var plainHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            long envelopeBytes = 0, done = 0;
            byte[] fixedHeader = Read(input, FixedHeaderSize, cipherHash, ref envelopeBytes);
            Require(fixedHeader.AsSpan(0, 8).SequenceEqual(Magic) && fixedHeader[8] == 1 && fixedHeader[9] == 1 &&
                fixedHeader[10] == 0 && fixedHeader[11] == 0, "Unsupported backup format/algorithms.");
            Require(BinaryPrimitives.ReadUInt32BigEndian(fixedHeader.AsSpan(12)) == ChunkSize,
                "Unsupported chunk size.");
            Require(BinaryPrimitives.ReadInt64BigEndian(fixedHeader.AsSpan(16)) == expectedLength,
                "Backup length differs from trusted manifest.");
            int identitySize = BinaryPrimitives.ReadUInt16BigEndian(fixedHeader.AsSpan(24));
            int wrappedSize = BinaryPrimitives.ReadUInt16BigEndian(fixedHeader.AsSpan(26));
            Require(identitySize >= 1 && identitySize <= 256 && wrappedSize == recipient.KeySize / 8,
                "Invalid bounded envelope header.");
            Require(CryptographicOperations.FixedTimeEquals(fixedHeader.AsSpan(36, 32),
                SHA256.HashData(recipient.ExportSubjectPublicKeyInfo())), "Recipient fingerprint differs.");
            byte[] context = Read(input, identitySize, cipherHash, ref envelopeBytes);
            Require(context.AsSpan().SequenceEqual(expectedIdentityBytes), "Backup identity differs from trusted manifest.");
            byte[] wrapped = Read(input, wrappedSize, cipherHash, ref envelopeBytes);
            byte[] header = new byte[FixedHeaderSize + identitySize + wrappedSize];
            fixedHeader.CopyTo(header, 0); context.CopyTo(header, FixedHeaderSize);
            wrapped.CopyTo(header, FixedHeaderSize + identitySize);
            byte[] headerHash = SHA256.HashData(header);
            byte[] prefix = fixedHeader.AsSpan(28, 8).ToArray();
            byte[] contentKey = recipient.Decrypt(wrapped, RSAEncryptionPadding.OaepSHA256);
            byte[] plain = new byte[ChunkSize];
            try
            {
                Require(contentKey.Length == 32, "Wrapped content key has an invalid size.");
                using var aes = new AesGcm(contentKey, TagSize);
                uint index = 0;
                while (true)
                {
                    uint size = BinaryPrimitives.ReadUInt32BigEndian(Read(input, 4, cipherHash, ref envelopeBytes));
                    Require(size <= ChunkSize, "Record length exceeds the bounded chunk size.");
                    if (size == 0)
                    {
                        Require(done == expectedLength, "Premature backup final marker.");
                        byte[] tag = Read(input, TagSize, cipherHash, ref envelopeBytes);
                        aes.Decrypt(Nonce(prefix, index), Array.Empty<byte>(), tag, Array.Empty<byte>(),
                            Aad(headerHash, index, 0));
                        Require(input.ReadByte() == -1, "Trailing data after backup final marker.");
                        byte[] actualHash = plainHash.GetHashAndReset();
                        Require(CryptographicOperations.FixedTimeEquals(actualHash, expectedHash),
                            "Plaintext hash differs from trusted manifest.");
                        return new Receipt {
                            Identity = expectedIdentity, RecipientSha256 = Hex(SHA256.HashData(recipient.ExportSubjectPublicKeyInfo())),
                            PlaintextBytes = done, EnvelopeBytes = envelopeBytes, PlaintextSha256 = Hex(actualHash),
                            EnvelopeSha256 = Hex(cipherHash.GetHashAndReset()), DataRecords = index
                        };
                    }
                    Require(index < uint.MaxValue && done < expectedLength &&
                        size == Math.Min(ChunkSize, expectedLength - done), "Invalid record sequence or length.");
                    byte[] cipher = Read(input, (int)size, cipherHash, ref envelopeBytes);
                    byte[] authTag = Read(input, TagSize, cipherHash, ref envelopeBytes);
                    aes.Decrypt(Nonce(prefix, index), cipher, authTag, plain.AsSpan(0, (int)size),
                        Aad(headerHash, index, size));
                    plainHash.AppendData(plain, 0, (int)size);
                    output.Write(plain, 0, (int)size); // Caller provides only Null or a private unpublished file.
                    CryptographicOperations.ZeroMemory(plain.AsSpan(0, (int)size));
                    done = checked(done + size);
                    index++;
                }
            }
            finally
            {
                CryptographicOperations.ZeroMemory(contentKey);
                CryptographicOperations.ZeroMemory(plain);
            }
        }

        public static Receipt Verify(Stream input, RSA recipient, long expectedLength, string identity, string expectedSha256)
            => Decrypt(input, Stream.Null, recipient, expectedLength, identity, expectedSha256);

        public static Receipt EncryptFile(Stream input, string outputPath, RSA recipient, long expectedLength, string identity)
        {
            return AtomicFile(outputPath, stream => Encrypt(input, stream, recipient, expectedLength, identity));
        }

        public static Receipt RestoreFile(Stream input, string outputPath, RSA recipient, long expectedLength,
            string identity, string expectedSha256)
        {
            return AtomicFile(outputPath, stream => Decrypt(input, stream, recipient, expectedLength, identity, expectedSha256));
        }

        private static Receipt AtomicFile(string outputPath, Func<Stream, Receipt> operation)
        {
            string full = SafeFiles.LocalPath(outputPath);
            string parent = Path.GetDirectoryName(full);
            using var pinned = SafeFiles.PinPrivateDirectory(parent);
            SafeFiles.RequireAbsent(full);
            string temporary = Path.Combine(parent, ".smkbkp-partial-" + Guid.NewGuid().ToString("N"));
            bool created = false;
            try
            {
                Receipt receipt;
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                    65536, FileOptions.WriteThrough))
                {
                    created = true;
                    SafeFiles.CheckOpenFile(output);
                    receipt = operation(output);
                    output.Flush(true);
                }
                // Same-directory rename, with no overwrite. Final file appears only after complete validation.
                File.Move(temporary, full, false);
                created = false;
                return receipt;
            }
            finally
            {
                if (created && File.Exists(temporary)) File.Delete(temporary);
            }
        }
    }

    public static class SafeFiles
    {
        private static SecurityIdentifier Owner => WindowsIdentity.GetCurrent().User;
        private static SecurityIdentifier SystemSid => new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);

        private const uint ReadAttributes = 0x80;
        private const uint ListDirectory = 0x01;
        private const uint GenericRead = 0x80000000;
        private const uint OpenExisting = 3;
        private const uint OpenReparsePoint = 0x00200000;
        private const uint BackupSemantics = 0x02000000;
        private const int FileAttributeTagInfo = 9;

        [StructLayout(LayoutKind.Sequential)]
        private struct AttributeTagInfo
        {
            public FileAttributes Attributes;
            public uint Tag;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SecurityAttributes
        {
            public int Length;
            public IntPtr Descriptor;
            public int InheritHandle;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
        private static extern SafeFileHandle CreateFileW(string path, uint access, FileShare sharing,
            IntPtr security, uint disposition, uint flags, IntPtr template);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int informationClass,
            out AttributeTagInfo information, uint size);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CreateDirectoryW(string path, ref SecurityAttributes security);

        internal static string LocalPath(string path)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows/NTFS is required.");
            if (!Path.IsPathFullyQualified(path) || path.StartsWith(@"\\", StringComparison.Ordinal)
                || path.IndexOf(':', 2) >= 0)
                throw new IOException("An absolute local path is required.");
            string full = Path.GetFullPath(path);
            if (!String.Equals(full, path, StringComparison.Ordinal) || Path.EndsInDirectorySeparator(full))
                throw new IOException("A normalized path naming a file or directory is required.");
            string root = Path.GetPathRoot(full);
            var drive = new DriveInfo(root);
            if (drive.DriveType == DriveType.Network || !String.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase))
                throw new IOException("Local NTFS is required.");
            foreach (string part in full.Substring(root.Length).Split(Path.DirectorySeparatorChar))
            {
                if (part.EndsWith('.') || part.EndsWith(' '))
                    throw new IOException("Ambiguous Windows path components are forbidden.");
            }
            return full;
        }

        private static SafeFileHandle OpenEntry(string path, uint access, bool allowMissing = false,
            FileShare sharing = FileShare.Read)
        {
            // OPEN_REPARSE_POINT exposes dangling links instead of following them.
            var handle = CreateFileW(path, access, sharing, IntPtr.Zero, OpenExisting,
                OpenReparsePoint | BackupSemantics, IntPtr.Zero);
            if (!handle.IsInvalid) return handle;
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            if (allowMissing && error == 2) return null;
            throw new IOException("Cannot open a backup path component.", new Win32Exception(error));
        }

        private static FileAttributes CheckedAttributes(SafeFileHandle handle)
        {
            if (!GetFileInformationByHandleEx(handle, FileAttributeTagInfo, out var information,
                (uint)Marshal.SizeOf<AttributeTagInfo>()))
                throw new IOException("Cannot read backup path attributes.", new Win32Exception(Marshal.GetLastWin32Error()));
            if ((information.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Reparse points are forbidden in backup paths.");
            return information.Attributes;
        }

        private sealed class DirectoryPins : IDisposable
        {
            private readonly List<SafeFileHandle> handles = new List<SafeFileHandle>();

            internal DirectoryPins(string path)
            {
                string current = Path.GetPathRoot(path);
                try
                {
                    AddDirectory(current);
                    foreach (string part in path.Substring(current.Length).Split(
                        Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
                    {
                        current = Path.Combine(current, part);
                        AddDirectory(current);
                    }
                }
                catch
                {
                    Dispose();
                    throw;
                }
            }

            private void AddDirectory(string path)
            {
                // Deny directory renames while allowing child creation and publication.
                var handle = OpenEntry(path, ListDirectory | ReadAttributes, sharing: FileShare.ReadWrite);
                handles.Add(handle);
                if ((CheckedAttributes(handle) & FileAttributes.Directory) == 0)
                    throw new IOException("Expected a backup path directory.");
            }

            public void Dispose()
            {
                for (int i = handles.Count - 1; i >= 0; i--) handles[i].Dispose();
            }
        }

        public static string NoLinks(string path)
        {
            string full = LocalPath(path);
            using var parents = new DirectoryPins(Path.GetDirectoryName(full));
            using var leaf = OpenEntry(full, ReadAttributes, allowMissing: true);
            if (leaf != null) CheckedAttributes(leaf);
            return full;
        }

        internal static void RequireAbsent(string path)
        {
            using var leaf = OpenEntry(path, ReadAttributes, allowMissing: true);
            if (leaf != null) throw new IOException("Output already exists.");
        }

        private static void CheckAcl(FileSystemSecurity acl, bool directory)
        {
            if (!Owner.Equals(acl.GetOwner(typeof(SecurityIdentifier)))) throw new IOException("Unexpected backup owner.");
            if (directory && !acl.AreAccessRulesProtected) throw new IOException("Private directory must disable inherited ACLs.");
            bool ownerFull = false, systemFull = false;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            {
                var sid = (SecurityIdentifier)rule.IdentityReference;
                if (rule.AccessControlType != AccessControlType.Allow || (!Owner.Equals(sid) && !SystemSid.Equals(sid)))
                    throw new IOException("Private backup ACL permits an unexpected identity or deny rule.");
                bool full = (rule.FileSystemRights & FileSystemRights.FullControl) == FileSystemRights.FullControl;
                if (Owner.Equals(sid) && full) ownerFull = true;
                if (SystemSid.Equals(sid) && full) systemFull = true;
            }
            if (!ownerFull || !systemFull) throw new IOException("Owner and SYSTEM full control are required.");
        }

        public static string CheckPrivateDirectory(string path)
        {
            string full = LocalPath(path);
            using var pinned = PinPrivateDirectory(full);
            return full;
        }

        public static IDisposable HoldPrivateDirectory(string path)
        {
            return PinPrivateDirectory(LocalPath(path));
        }

        internal static IDisposable PinPrivateDirectory(string full)
        {
            var pins = new DirectoryPins(full);
            try
            {
                CheckAcl(new DirectoryInfo(full).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access), true);
                return pins;
            }
            catch
            {
                pins.Dispose();
                throw;
            }
        }

        internal static void CheckOpenFile(FileStream stream)
        {
            CheckAcl(stream.GetAccessControl(), false);
        }

        public static string CheckPrivateFile(string path)
        {
            string full = LocalPath(path);
            using var stream = OpenPrivateRead(full);
            return full;
        }

        public static FileStream OpenPrivateRead(string path)
        {
            string full = LocalPath(path);
            using var parents = PinPrivateDirectory(Path.GetDirectoryName(full));
            var handle = OpenEntry(full, GenericRead);
            FileStream stream = null;
            try
            {
                if ((CheckedAttributes(handle) & FileAttributes.Directory) != 0)
                    throw new IOException("Expected a regular backup file.");
                stream = new FileStream(handle, FileAccess.Read);
                CheckOpenFile(stream);
                return stream;
            }
            catch
            {
                stream?.Dispose();
                handle.Dispose();
                throw;
            }
        }

        public static string CreatePrivateDirectory(string path)
        {
            string full = LocalPath(path);
            using var parents = new DirectoryPins(Path.GetDirectoryName(full));
            var acl = new DirectorySecurity();
            acl.SetOwner(Owner);
            acl.SetAccessRuleProtection(true, false);
            foreach (var sid in new[] { Owner, SystemSid })
                acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            // Win32 creation applies the ACL atomically and fails if the name already exists.
            byte[] descriptor = acl.GetSecurityDescriptorBinaryForm();
            var pinned = GCHandle.Alloc(descriptor, GCHandleType.Pinned);
            try
            {
                var security = new SecurityAttributes {
                    Length = Marshal.SizeOf<SecurityAttributes>(),
                    Descriptor = pinned.AddrOfPinnedObject()
                };
                if (!CreateDirectoryW(full, ref security))
                    throw new IOException("Cannot create a new private backup directory.", new Win32Exception(Marshal.GetLastWin32Error()));
            }
            finally { pinned.Free(); }
            return CheckPrivateDirectory(full);
        }

        private static void KeyFile(string path, byte[] bytes)
        {
            try
            {
                using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    CheckOpenFile(stream);
                    stream.Write(bytes); stream.Flush(true);
                }
            }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }

        public static string GenerateRecipient(string outputDirectory, int bits)
        {
            if (bits < 3072 || bits > 8192 || bits % 256 != 0) throw new ArgumentException("RSA size must be 3072..8192 bits, multiple of256.");
            string full = CreatePrivateDirectory(outputDirectory);
            using var pinned = PinPrivateDirectory(full);
            using var rsa = RSA.Create(bits);
            string fingerprint = Convert.ToHexString(SHA256.HashData(rsa.ExportSubjectPublicKeyInfo())).ToLowerInvariant();
            KeyFile(Path.Combine(full, "recipient-private.pk8"), rsa.ExportPkcs8PrivateKey());
            KeyFile(Path.Combine(full, "recipient-public.spki"), rsa.ExportSubjectPublicKeyInfo());
            return fingerprint;
        }

        public static RSA LoadRecipient(string path, bool privateKey)
        {
            using var stream = OpenPrivateRead(path);
            long length = stream.Length;
            if (length < 100 || length > 16384) throw new IOException("Unexpected key-file size.");
            byte[] bytes = new byte[(int)length];
            RSA rsa = RSA.Create();
            try
            {
                stream.ReadExactly(bytes);
                int consumed;
                if (privateKey) rsa.ImportPkcs8PrivateKey(bytes, out consumed);
                else rsa.ImportSubjectPublicKeyInfo(bytes, out consumed);
                if (consumed != bytes.Length || rsa.KeySize < 3072 || rsa.KeySize > 8192)
                    throw new CryptographicException("Invalid recipient-key encoding/size.");
                return rsa;
            }
            catch { rsa.Dispose(); throw; }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }
    }
}
