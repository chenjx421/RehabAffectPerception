"""Vault security contract using synthetic bytes and isolated temporary roots.

No real database, document directory, server, network or package installation.
Native DPAPI tests are Windows-only; other key lifecycle tests use an explicitly
test-only authenticated wrapper so they also exercise filesystem code on POSIX.
"""
from __future__ import annotations

import base64
import builtins
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

from rehab_affect import demo2_dossier_vault as vault


@pytest.fixture(autouse=True)
def env_key(monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv(vault.KEY_ENV, key.decode("ascii"))
    return key


@pytest.fixture
def root(tmp_path):
    return tmp_path / "scoped_dossier_v1"


@pytest.fixture
def wrapped_mode(monkeypatch):
    """Never persist this test-only wrapping key; not a production fallback."""
    wrapper = Fernet(Fernet.generate_key())
    monkeypatch.delenv(vault.KEY_ENV)
    monkeypatch.setattr(vault, "_IS_WINDOWS", True)

    def fake_dpapi(data, *, decrypt):
        try:
            return wrapper.decrypt(data) if decrypt else wrapper.encrypt(data)
        except Exception:
            raise vault.VaultError("vault_key_corrupt") from None

    monkeypatch.setattr(vault, "_dpapi", fake_dpapi)


def _key_file(root):
    matches = list((root.parent / vault._KEY_DIRECTORY).glob("*.dpapi"))
    assert len(matches) == 1
    return matches[0]


def _assert_unavailable(instance, code=None):
    assert instance.status() == {"available": False, "mode": "unavailable"}
    with pytest.raises(vault.VaultError) as caught:
        instance.seal(b"synthetic only")
    if code:
        assert caught.value.code == code
    assert caught.value.message == vault._MESSAGES[caught.value.code]
    return caught.value


def test_constructor_is_lazy(root):
    vault.DossierVault(root)
    assert not root.exists()
    assert not (root.parent / vault._KEY_DIRECTORY).exists()


@pytest.mark.parametrize("data", [b"", b"a", bytes(range(256)), "合成教学资料".encode()])
def test_env_fernet_roundtrip_and_independent_reopen(root, env_key, data):
    instance = vault.DossierVault(root)
    assert instance.status() == {"available": True, "mode": "env_fernet"}
    first, second = instance.seal(data), instance.seal(data)
    assert first != second
    assert Fernet(env_key).decrypt(first) == data
    assert instance.open(second) == data
    assert vault.DossierVault(root).open(first) == data
    assert not (root.parent / vault._KEY_DIRECTORY).exists()
    assert list(root.iterdir()) == []


def test_environment_has_priority_over_dpapi(root, monkeypatch):
    monkeypatch.setattr(vault, "_dpapi", lambda *a, **kw: pytest.fail("DPAPI must not run"))
    assert vault.DossierVault(root).status()["mode"] == "env_fernet"


@pytest.mark.parametrize("bad_key", ["", "secret-key", "中文", "A" * 43,
                                     "A" * 44, "A" * 42 + "B=", " A" + "A" * 42 + "="])
def test_invalid_explicit_key_never_falls_back_or_creates_files(root, monkeypatch, bad_key):
    monkeypatch.setenv(vault.KEY_ENV, bad_key)
    monkeypatch.setattr(vault, "_dpapi", lambda *a, **kw: pytest.fail("no fallback"))
    _assert_unavailable(vault.DossierVault(root), "vault_key_invalid")
    assert not root.exists()
    assert not (root.parent / vault._KEY_DIRECTORY).exists()


def test_non_windows_without_env_fails_closed_without_writes(root, monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV)
    monkeypatch.setattr(vault, "_IS_WINDOWS", False)
    _assert_unavailable(vault.DossierVault(root), "vault_key_required")
    assert not root.exists()
    assert not (root.parent / vault._KEY_DIRECTORY).exists()


def test_changing_env_key_does_not_decrypt_old_ciphertext(root, monkeypatch):
    instance = vault.DossierVault(root)
    token = instance.seal(b"synthetic student-support note")
    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())
    with pytest.raises(vault.VaultError, match=vault._MESSAGES["vault_decrypt_failed"]):
        instance.open(token)


@pytest.mark.parametrize("method", ["seal", "open"])
@pytest.mark.parametrize("data", [None, "plaintext", bytearray(b"data"), memoryview(b"data"), 7])
def test_only_bytes_are_accepted(root, method, data):
    with pytest.raises(vault.VaultError) as caught:
        getattr(vault.DossierVault(root), method)(data)
    assert caught.value.code == "vault_input_invalid"
    assert not root.exists()


@pytest.mark.parametrize("token", [b"", b"not-a-fernet-token", b"gAAAAA=="])
def test_malformed_token_fails_closed(root, token):
    with pytest.raises(vault.VaultError) as caught:
        vault.DossierVault(root).open(token)
    assert caught.value.code == "vault_decrypt_failed"


@pytest.mark.parametrize("index", [0, 1, 10, 25, -1])
def test_ciphertext_tampering_is_detected(root, index):
    instance = vault.DossierVault(root)
    token = instance.seal(b"synthetic confidential educational support")
    decoded = bytearray(base64.urlsafe_b64decode(token))
    decoded[index] ^= 1
    with pytest.raises(vault.VaultError) as caught:
        instance.open(base64.urlsafe_b64encode(decoded))
    assert caught.value.code == "vault_decrypt_failed"


def test_size_limit_matches_bounded_encryption_envelope_fernet_boundary(root):
    instance = vault.DossierVault(root)
    plaintext = b"x" * vault.MAX_PLAINTEXT_BYTES
    token = instance.seal(plaintext)
    assert len(token) == vault.MAX_CIPHERTEXT_BYTES
    assert instance.open(token) == plaintext
    for method, data in [(instance.seal, plaintext + b"x"),
                         (instance.open, b"x" * (vault.MAX_CIPHERTEXT_BYTES + 1))]:
        with pytest.raises(vault.VaultError) as caught:
            method(data)
        assert caught.value.code == "vault_data_too_large"


def test_eight_mib_original_with_authenticated_document_id_envelope_is_accepted(root):
    assert vault.MAX_DOCUMENT_BYTES == 8 * 1024 * 1024
    assert vault.ENVELOPE_ALLOWANCE_BYTES == 1024
    assert vault.MAX_PLAINTEXT_BYTES == vault.MAX_DOCUMENT_BYTES + 1024
    # Matches the store's opaque 32-character ID + NUL + original bytes.
    original = b"x" * vault.MAX_DOCUMENT_BYTES
    envelope = b"0123456789abcdef0123456789abcdef\0" + original
    instance = vault.DossierVault(root)
    assert instance.open(instance.seal(envelope)) == envelope


def test_decrypted_size_is_checked_even_when_token_fits_boundary(root, env_key):
    token = Fernet(env_key).encrypt(b"x" * (vault.MAX_PLAINTEXT_BYTES + 1))
    assert len(token) == vault.MAX_CIPHERTEXT_BYTES
    with pytest.raises(vault.VaultError) as caught:
        vault.DossierVault(root).open(token)
    assert caught.value.code == "vault_data_too_large"


@pytest.mark.parametrize("root_kind", ["relative", "anchor", "parent", "reserved", "stream",
                                        "trailing_dot", "trailing_space", "control", "key_directory", "string"])
def test_unsafe_roots_rejected_before_writes(tmp_path, root_kind):
    paths = {
        "relative": Path("relative-dossier"), "anchor": Path(tmp_path.anchor),
        "parent": tmp_path / "child" / ".." / "escaped",
        "reserved": tmp_path / "NUL.txt", "stream": tmp_path / "data:stream",
        "trailing_dot": tmp_path / "data.", "trailing_space": tmp_path / "data ",
        "control": tmp_path / "data\n", "key_directory": tmp_path / vault._KEY_DIRECTORY,
        "string": str(tmp_path / "data"),
    }
    _assert_unavailable(vault.DossierVault(paths[root_kind]), "vault_path_invalid")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows UNC and device path syntax")
@pytest.mark.parametrize("raw", [r"\\server\share\dossier", r"\\?\C:\dossier", r"\\.\C:\dossier"])
def test_unc_and_device_paths_rejected_without_access(raw):
    _assert_unavailable(vault.DossierVault(Path(raw)), "vault_path_invalid")


def test_root_file_and_file_ancestor_rejected(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_bytes(b"untouched")
    for root in [path, path / "dossier"]:
        _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")
    assert path.read_bytes() == b"untouched"


@pytest.mark.parametrize("at_root", [True, False])
def test_actual_symlink_directory_rejected(tmp_path, at_root):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("OS does not permit unprivileged symlink creation")
    root = link if at_root else link / "child"
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")
    assert list(outside.iterdir()) == []


def test_windows_reparse_attribute_is_rejected_even_without_symlink_mode(root, monkeypatch):
    root.mkdir()
    original = Path.lstat

    def fake_lstat(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")


def test_directory_permission_error_is_sanitized(root, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("synthetic-sensitive-file-name and key must not escape")

    monkeypatch.setattr(vault, "_directory_tree", denied)
    error = _assert_unavailable(vault.DossierVault(root), "vault_key_unavailable")
    assert "synthetic" not in repr(error)


def test_missing_cryptography_fails_closed_without_files(root, monkeypatch):
    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "cryptography.fernet":
            raise ImportError("synthetic sensitive installation path")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    _assert_unavailable(vault.DossierVault(root), "vault_unavailable")
    assert not root.exists()


@pytest.mark.parametrize("method,code", [("seal", "vault_encrypt_failed"),
                                        ("open", "vault_decrypt_failed")])
def test_cipher_provider_errors_are_sanitized(root, monkeypatch, method, code):
    def failed(data):
        raise RuntimeError("synthetic secret provider detail")

    instance = vault.DossierVault(root)
    monkeypatch.setattr(instance, "_cipher", lambda: (
        SimpleNamespace(encrypt=failed, decrypt=failed), "env_fernet"))
    with pytest.raises(vault.VaultError) as caught:
        getattr(instance, method)(b"synthetic input")
    assert caught.value.code == code
    assert "synthetic" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_wrapped_key_persists_outside_documents_and_reopens(root, wrapped_mode, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setattr(Fernet, "generate_key", staticmethod(lambda: key))
    instance = vault.DossierVault(root)
    token = instance.seal(b"synthetic note not to appear on disk")
    path = _key_file(root)
    assert path.parent == root.parent / vault._KEY_DIRECTORY
    assert not path.is_relative_to(root)
    assert list(root.iterdir()) == []
    stored = path.read_bytes()
    assert stored.startswith(vault._KEY_MAGIC)
    assert key not in stored
    assert b"synthetic note" not in stored
    assert vault.DossierVault(root).open(token) == b"synthetic note not to appear on disk"
    assert instance.status() == {"available": True, "mode": "windows_dpapi"}
    assert path.read_bytes() == stored
    assert len(list(path.parent.iterdir())) == 1


@pytest.mark.parametrize("corruption", [b"", b"bad header", vault._KEY_MAGIC + b"invalid wrapped data",
                                        b"x" * (vault.MAX_WRAPPED_KEY_BYTES + 1)])
def test_corrupt_key_never_regenerated_or_overwritten(root, wrapped_mode, monkeypatch, corruption):
    instance = vault.DossierVault(root)
    instance.seal(b"synthetic note")
    path = _key_file(root)
    path.write_bytes(corruption)
    monkeypatch.setattr(Fernet, "generate_key", staticmethod(lambda: pytest.fail("no regeneration")))
    _assert_unavailable(instance, "vault_key_corrupt")
    _assert_unavailable(vault.DossierVault(root), "vault_key_corrupt")
    assert path.read_bytes() == corruption


def test_valid_wrapper_containing_invalid_fernet_key_fails_closed(root, wrapped_mode, monkeypatch):
    vault.DossierVault(root).seal(b"synthetic")
    monkeypatch.setattr(vault, "_dpapi", lambda *args, **kwargs: b"not-a-key")
    _assert_unavailable(vault.DossierVault(root), "vault_key_corrupt")


def test_existing_key_directory_instead_of_file_is_not_replaced(root, wrapped_mode):
    vault.DossierVault(root).seal(b"synthetic")
    path = _key_file(root)
    path.unlink()
    path.mkdir()
    _assert_unavailable(vault.DossierVault(root), "vault_key_corrupt")
    assert path.is_dir()


def test_reparse_key_file_is_rejected(root, wrapped_mode, monkeypatch):
    vault.DossierVault(root).seal(b"synthetic")
    path = _key_file(root)
    before = path.read_bytes()
    original = Path.lstat

    def fake_lstat(candidate, *args, **kwargs):
        if candidate == path:
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=0x400)
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    _assert_unavailable(vault.DossierVault(root), "vault_key_corrupt")
    assert path.read_bytes() == before


def test_existing_key_directory_reparse_is_rejected(root, wrapped_mode, monkeypatch):
    vault.DossierVault(root).seal(b"synthetic")
    directory = root.parent / vault._KEY_DIRECTORY
    original = Path.lstat

    def fake_lstat(path, *args, **kwargs):
        if path == directory:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")


@pytest.mark.parametrize("stage", ["open", "after_read"])
def test_disappearing_existing_key_never_triggers_regeneration(root, wrapped_mode, monkeypatch, stage):
    vault.DossierVault(root).seal(b"synthetic")
    path = _key_file(root)
    monkeypatch.setattr(Fernet, "generate_key", staticmethod(lambda: pytest.fail("no regeneration")))
    original_open, original_lstat = os.open, Path.lstat
    calls = 0

    def disappearing_open(candidate, *args, **kwargs):
        if candidate == path and stage == "open":
            raise FileNotFoundError("synthetic removed key")
        return original_open(candidate, *args, **kwargs)

    def disappearing_after(candidate, *args, **kwargs):
        nonlocal calls
        if candidate == path:
            calls += 1
            if calls % 2 == 0:
                raise FileNotFoundError("synthetic removed key")
        return original_lstat(candidate, *args, **kwargs)

    monkeypatch.setattr(os, "open", disappearing_open)
    if stage == "after_read":
        monkeypatch.setattr(Path, "lstat", disappearing_after)
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")


def test_key_inode_replacement_is_rejected(root, wrapped_mode, monkeypatch):
    vault.DossierVault(root).seal(b"synthetic")
    original = os.fstat

    def replaced(descriptor):
        info = original(descriptor)
        return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev, st_ino=info.st_ino + 1)

    monkeypatch.setattr(os, "fstat", replaced)
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")


def test_atomic_publication_failure_leaves_no_final_key_or_temporary(root, wrapped_mode, monkeypatch):
    def no_hardlinks(*args, **kwargs):
        raise OSError("private synthetic path; hardlinks unsupported")

    monkeypatch.setattr(os, "link", no_hardlinks)
    _assert_unavailable(vault.DossierVault(root), "vault_key_unavailable")
    assert list((root.parent / vault._KEY_DIRECTORY).iterdir()) == []
    assert list(root.iterdir()) == []


def test_independent_roots_use_different_keys(tmp_path, wrapped_mode):
    first, second = tmp_path / "first", tmp_path / "second"
    token = vault.DossierVault(first).seal(b"synthetic")
    with pytest.raises(vault.VaultError) as caught:
        vault.DossierVault(second).open(token)
    assert caught.value.code == "vault_decrypt_failed"
    assert len(list((tmp_path / vault._KEY_DIRECTORY).glob("*.dpapi"))) == 2


def _concurrent_roundtrip(root, workers=8):
    start = Barrier(workers)

    def work(index):
        start.wait(timeout=15)
        payload = ("synthetic-" + str(index)).encode()
        return payload, vault.DossierVault(root).seal(payload)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, range(workers)))
    fresh = vault.DossierVault(root)
    for plaintext, token in results:
        assert fresh.open(token) == plaintext
    assert len(list((root.parent / vault._KEY_DIRECTORY).iterdir())) == 1


def test_concurrent_independent_initializers_share_winning_key(root, wrapped_mode):
    _concurrent_roundtrip(root)


@pytest.mark.skipif(os.name != "nt", reason="Requires native current-user Windows DPAPI")
def test_native_dpapi_reopen_current_user_and_ciphertext_at_rest(root, monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV)
    key = Fernet.generate_key()
    monkeypatch.setattr(Fernet, "generate_key", staticmethod(lambda: key))
    token = vault.DossierVault(root).seal(b"synthetic Windows only")
    path = _key_file(root)
    assert key not in path.read_bytes()
    assert b"synthetic Windows only" not in path.read_bytes()
    assert vault.DossierVault(root).open(token) == b"synthetic Windows only"
    assert vault.DossierVault(root).status() == {"available": True, "mode": "windows_dpapi"}
    path.write_bytes(vault._KEY_MAGIC + b"broken DPAPI ciphertext")
    _assert_unavailable(vault.DossierVault(root), "vault_key_corrupt")


@pytest.mark.skipif(os.name != "nt", reason="Requires native current-user Windows DPAPI")
def test_native_dpapi_concurrent_independent_initializers(root, monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV)
    _concurrent_roundtrip(root)


@pytest.mark.skipif(os.name != "nt", reason="Requires native current-user Windows DPAPI")
def test_native_dpapi_independent_process_creation_and_reopen(root, monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV)
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(Path(vault.__file__).parent.parent)
    program = (
        "import sys; from pathlib import Path; "
        "from rehab_affect.demo2_dossier_vault import DossierVault; "
        "v=DossierVault(Path(sys.argv[1])); "
        "print(v.seal(b'synthetic process payload').decode('ascii'))"
    )
    # Simultaneous fresh processes exercise atomic publication across processes.
    children = [subprocess.Popen([sys.executable, "-B", "-c", program, str(root)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=child_env, text=True) for _ in range(4)]
    try:
        results = [child.communicate(timeout=30) for child in children]
        assert all(child.returncode == 0 for child in children)
        for token, stderr in results:
            assert not stderr
            assert vault.DossierVault(root).open(token.strip().encode()) == b"synthetic process payload"
        assert len(list((root.parent / vault._KEY_DIRECTORY).iterdir())) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)


@pytest.mark.parametrize("decrypt", [False, True])
def test_dpapi_calls_are_current_user_ui_forbidden_and_release_output(monkeypatch, decrypt):
    returned = b"synthetic native output"
    allocation = (ctypes.c_ubyte * len(returned)).from_buffer_copy(returned)
    calls = []

    class NativeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def transform(source, description, entropy, reserved, prompt, flags, output):
        assert flags == 0x1  # UI forbidden; LOCAL_MACHINE (0x4) absent.
        assert reserved is None and prompt is None
        assert description is None if decrypt else description == "RehabAffect dossier key v1"
        source_blob = ctypes.cast(source, ctypes.POINTER(vault._DataBlob)).contents
        entropy_blob = ctypes.cast(entropy, ctypes.POINTER(vault._DataBlob)).contents
        assert ctypes.string_at(source_blob.pbData, source_blob.cbData) == b"synthetic source"
        assert ctypes.string_at(entropy_blob.pbData, entropy_blob.cbData) == vault._DPAPI_ENTROPY
        result = ctypes.cast(output, ctypes.POINTER(vault._DataBlob)).contents
        result.cbData = len(returned)
        result.pbData = ctypes.cast(allocation, ctypes.POINTER(ctypes.c_ubyte))
        calls.append("transform")
        return 1

    def release(pointer):
        assert bytes(allocation) == b"\0" * len(returned)
        calls.append("release")

    native = SimpleNamespace(CryptProtectData=NativeFunction(transform),
                             CryptUnprotectData=NativeFunction(transform),
                             LocalFree=NativeFunction(release))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: native, raising=False)
    assert vault._dpapi(b"synthetic source", decrypt=decrypt) == returned
    assert calls == ["transform", "release"]


@pytest.mark.skipif(os.name != "nt", reason="Windows drive classification")
@pytest.mark.parametrize("drive_type", [0, 1, 4, 5])
def test_network_unknown_and_non_writable_drives_rejected(root, monkeypatch, drive_type):
    class DriveType:
        def __call__(self, anchor):
            assert anchor == root.anchor
            return drive_type

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs:
                        SimpleNamespace(GetDriveTypeW=DriveType()))
    _assert_unavailable(vault.DossierVault(root), "vault_path_invalid")
    assert not root.exists()


def test_errors_and_status_never_disclose_secrets(root, env_key, caplog, capsys, monkeypatch):
    private = "synthetic confidential source reference"
    error = vault.VaultError("unknown-code", private + env_key.decode() + str(root))
    assert error.code == "vault_unavailable"
    assert error.message == vault._MESSAGES["vault_unavailable"]
    instance = vault.DossierVault(root)
    instance.seal(private.encode())
    monkeypatch.setenv(vault.KEY_ENV, private)
    safe_error = _assert_unavailable(instance)
    rendered = json.dumps(instance.status()) + str(safe_error) + repr(error)
    captured = capsys.readouterr()
    rendered += captured.out + captured.err + caplog.text
    for sensitive in [private, env_key.decode(), str(root)]:
        assert sensitive not in rendered
    assert not captured.out and not captured.err and not caplog.text
