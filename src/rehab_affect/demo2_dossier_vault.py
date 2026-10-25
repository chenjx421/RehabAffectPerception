"""Authenticated encryption for scoped dossier content; no authorization policy.

Only seal/open/status are public. An explicitly configured Fernet key always
takes precedence (including an invalid/empty value, which fails closed).
Otherwise Windows stores a DPAPI CURRENT-USER-wrapped key in a sibling key
directory, never under the document root and never as plaintext. There is no
key download, logging, legacy migration, or automatic key rotation/recovery.

DPAPI protects against other OS users, not malicious code running as this user.
The store remains responsible for scoped access, file writes and retention.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any
from uuid import uuid4


KEY_ENV = "REHAB_DEMO2_DOSSIER_KEY"
# Encryption-layer budget only: the store still limits the ORIGINAL upload to
# 8 MiB. Leave bounded room for its authenticated document-ID/content envelope.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
ENVELOPE_ALLOWANCE_BYTES = 1024
MAX_PLAINTEXT_BYTES = MAX_DOCUMENT_BYTES + ENVELOPE_ALLOWANCE_BYTES
MAX_CIPHERTEXT_BYTES = 4 * ((57 + 16 * (MAX_PLAINTEXT_BYTES // 16 + 1) + 2) // 3)
MAX_WRAPPED_KEY_BYTES = 16 * 1024
_KEY_DIRECTORY = ".demo2_dossier_keys"
_KEY_MAGIC = b"RAP-DOSSIER-DPAPI-V1\x00"
_DPAPI_ENTROPY = b"RehabAffectPerception/scoped-dossier-v1/key"
_IS_WINDOWS = os.name == "nt"
_MESSAGES = {
    "vault_unavailable": "资料加密服务暂不可用",
    "vault_key_required": "未配置可用的资料加密密钥",
    "vault_key_invalid": "资料加密密钥配置无效",
    "vault_key_unavailable": "资料加密密钥无法安全保存或读取",
    "vault_key_corrupt": "资料加密密钥文件损坏或无法解锁",
    "vault_path_invalid": "资料加密存储路径不可用",
    "vault_input_invalid": "资料加密输入格式无效",
    "vault_data_too_large": "资料加密输入超过大小限制",
    "vault_encrypt_failed": "资料加密失败",
    "vault_decrypt_failed": "资料无法解密或完整性校验失败",
}


class VaultError(Exception):
    """Safe error contract; arbitrary caller/provider messages are not exposed."""

    def __init__(self, code: str, message: str = ""):
        self.code = code if code in _MESSAGES else "vault_unavailable"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def _error(code: str) -> VaultError:
    return VaultError(code, _MESSAGES[code])


def _check_local_drive(anchor: str) -> None:
    if os.name != "nt":
        return
    try:
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
        function.argtypes = [wintypes.LPCWSTR]
        function.restype = wintypes.UINT
        # Reject mapped network drives, unknown drives and inaccessible roots.
        if function(anchor) not in (2, 3, 6):  # removable, fixed, RAM disk
            raise _error("vault_path_invalid")
    except VaultError:
        raise
    except Exception:
        raise _error("vault_path_invalid") from None


def _local_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise _error("vault_path_invalid")
    raw = str(root)
    if (not root.is_absolute() or raw.startswith(("\\\\", "//"))
            or root == root.parent or ".." in root.parts
            or root.name.casefold() == _KEY_DIRECTORY.casefold()):
        raise _error("vault_path_invalid")
    # Reject device/alternate-stream names and Windows normalization aliases.
    for part in root.parts[1:]:
        stem = part.split(".", 1)[0].upper()
        if (":" in part or any(ord(char) < 32 for char in part)
                or part != part.rstrip(" .")
                or stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                            *(f"LPT{i}" for i in range(1, 10))}):
            raise _error("vault_path_invalid")
    _check_local_drive(root.anchor)
    return root


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _directory_tree(path: Path, *, create: bool) -> None:
    """Check every ancestor without resolve(), which would hide link traversal."""
    current = Path(path.anchor)
    for part in (None, *path.parts[1:]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not create:
                raise _error("vault_path_invalid") from None
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass  # A concurrent initializer must still pass the checks.
            info = current.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise _error("vault_path_invalid")


def _read_key_file(path: Path) -> bytes:
    _directory_tree(path.parent, create=False)
    before = path.lstat()
    if _is_link(before) or not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_WRAPPED_KEY_BYTES:
        raise _error("vault_key_corrupt")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        # Only absence at the FIRST lstat allows initialization. Disappearance
        # after observing an existing key must not silently create a new key.
        raise _error("vault_path_invalid") from None
    try:
        opened = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or not stat.S_ISREG(opened.st_mode)):
            raise _error("vault_path_invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_WRAPPED_KEY_BYTES + 1)
        _directory_tree(path.parent, create=False)
        try:
            after = path.lstat()
        except FileNotFoundError:
            raise _error("vault_path_invalid") from None
        if _is_link(after) or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
            raise _error("vault_path_invalid")
    finally:
        os.close(descriptor)
    if len(data) > MAX_WRAPPED_KEY_BYTES or not data.startswith(_KEY_MAGIC) or len(data) <= len(_KEY_MAGIC):
        raise _error("vault_key_corrupt")
    return data[len(_KEY_MAGIC):]


def _publish_key(path: Path, wrapped: bytes) -> None:
    """Publish COMPLETE DPAPI ciphertext atomically, without replacing a winner.

    Exclusive temporary creation + hard-link publication is atomic across
    independent processes. The only on-disk bytes are DPAPI ciphertext. A
    filesystem without hard-link support fails closed; no plaintext fallback.
    """
    data = _KEY_MAGIC + wrapped
    if not wrapped or len(data) > MAX_WRAPPED_KEY_BYTES:
        raise _error("vault_key_unavailable")
    _directory_tree(path.parent, create=False)
    temporary = path.parent / (".key-" + uuid4().hex + ".tmp")
    descriptor = None
    identity = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(descriptor)
        identity = (info.st_dev, info.st_ino)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _directory_tree(path.parent, create=False)
        info = temporary.lstat()
        if _is_link(info) or (info.st_dev, info.st_ino) != identity:
            raise _error("vault_path_invalid")
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            pass  # Read the winning key, NEVER use the losing generated key.
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if identity is not None:
            # Never unlink an attacker-replaced path or traverse a new junction.
            _directory_tree(path.parent, create=False)
            try:
                info = temporary.lstat()
                if _is_link(info) or (info.st_dev, info.st_ino) != identity:
                    raise _error("vault_path_invalid")
                temporary.unlink()
            except FileNotFoundError:
                pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    """UI-forbidden current-user DPAPI; never CRYPTPROTECT_LOCAL_MACHINE."""
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        entropy_buffer = (ctypes.c_ubyte * len(_DPAPI_ENTROPY)).from_buffer_copy(_DPAPI_ENTROPY)
        source = _DataBlob(len(data), source_buffer)
        entropy = _DataBlob(len(_DPAPI_ENTROPY), entropy_buffer)
        output = _DataBlob()
        if decrypt:
            function = crypt32.CryptUnprotectData
            function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
            description = None
        else:
            function = crypt32.CryptProtectData
            function.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
            description = "RehabAffect dossier key v1"
        function.restype = wintypes.BOOL
        try:
            success = function(ctypes.byref(source), description, ctypes.byref(entropy), None, None,
                               0x1, ctypes.byref(output))  # CRYPTPROTECT_UI_FORBIDDEN only.
            if not success or not output.pbData or not 0 < output.cbData <= MAX_WRAPPED_KEY_BYTES:
                raise _error("vault_key_corrupt" if decrypt else "vault_key_unavailable")
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                if 0 < output.cbData <= MAX_WRAPPED_KEY_BYTES:
                    ctypes.memset(output.pbData, 0, output.cbData)
                local_free(ctypes.cast(output.pbData, ctypes.c_void_p))
            ctypes.memset(source_buffer, 0, len(data))
    except VaultError:
        raise
    except Exception:
        raise _error("vault_key_corrupt" if decrypt else "vault_key_unavailable") from None


def _fernet(key: Any):
    try:
        if isinstance(key, str):
            key = key.encode("ascii")
        if not isinstance(key, bytes) or not re.fullmatch(rb"[A-Za-z0-9_-]{43}=", key):
            raise ValueError
        decoded = base64.b64decode(key, altchars=b"-_", validate=True)
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != key:
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise _error("vault_key_invalid") from None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key)
    except (ImportError, OSError):
        raise _error("vault_unavailable") from None


class DossierVault:
    """Lazy setup: construction alone does not access a key or touch the disk.

    status() returns exactly {available, mode}, where mode is env_fernet,
    windows_dpapi, or unavailable. seal/open raise only safe VaultError failures.
    The key/path are revalidated on each operation; corrupt keys are not silently
    replaced. Expiry, purpose and who may read plaintext belong to the store.
    """

    def __init__(self, root: Path):
        self._root = root
        self._lock = RLock()

    def _cipher(self):
        try:
            root = _local_root(self._root)
            configured = os.environ.get(KEY_ENV)
            # Reject unsupported or invalid configuration BEFORE creating files.
            if configured is not None:
                cipher = _fernet(configured)
                _directory_tree(root, create=True)
                return cipher, "env_fernet"
            if not _IS_WINDOWS:
                raise _error("vault_key_required")
            # Check dependency before making a persistent key.
            from cryptography.fernet import Fernet
            _directory_tree(root, create=True)
            keys = root.parent / _KEY_DIRECTORY
            _directory_tree(keys, create=True)
            identifier = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
            path = keys / (identifier + ".dpapi")
            try:
                wrapped = _read_key_file(path)
            except FileNotFoundError:
                wrapped = _dpapi(Fernet.generate_key(), decrypt=False)
                _publish_key(path, wrapped)
                wrapped = _read_key_file(path)
            key = _dpapi(wrapped, decrypt=True)
            try:
                cipher = _fernet(key)
            except VaultError:
                raise _error("vault_key_corrupt") from None
            return cipher, "windows_dpapi"
        except VaultError:
            raise
        except (ImportError, OSError, ValueError, TypeError, RuntimeError):
            raise _error("vault_key_unavailable") from None

    def status(self) -> dict[str, Any]:
        with self._lock:
            try:
                _, mode = self._cipher()
                return {"available": True, "mode": mode}
            except VaultError:
                return {"available": False, "mode": "unavailable"}

    def seal(self, data: bytes) -> bytes:
        if not isinstance(data, bytes):
            raise _error("vault_input_invalid")
        if len(data) > MAX_PLAINTEXT_BYTES:
            raise _error("vault_data_too_large")
        with self._lock:
            cipher, _ = self._cipher()
            try:
                return cipher.encrypt(data)
            except Exception:
                raise _error("vault_encrypt_failed") from None

    def open(self, data: bytes) -> bytes:
        if not isinstance(data, bytes):
            raise _error("vault_input_invalid")
        if len(data) > MAX_CIPHERTEXT_BYTES:
            raise _error("vault_data_too_large")
        with self._lock:
            cipher, _ = self._cipher()
            try:
                plaintext = cipher.decrypt(data)
                if len(plaintext) > MAX_PLAINTEXT_BYTES:
                    raise _error("vault_data_too_large")
                return plaintext
            except VaultError:
                raise
            except Exception:
                raise _error("vault_decrypt_failed") from None
