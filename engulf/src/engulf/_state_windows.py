from __future__ import annotations

import ctypes
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never, cast

from engulf_api import LockTimeoutError, StateCatalogError

from ._state_platform import _HeldFileLock, _StateOwner

_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_IO_PENDING = 997
_ERROR_LOCK_VIOLATION = 33
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
_LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1
_SDDL_REVISION_1 = 1
_INVALID_HANDLE_VALUE = cast(int, ctypes.c_void_p(-1).value)


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD))


class _TokenUser(ctypes.Structure):
    _fields_ = (("user", _SidAndAttributes),)


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    )


class _Overlapped(ctypes.Structure):
    _fields_ = (
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", wintypes.DWORD),
        ("offset_high", wintypes.DWORD),
        ("event", wintypes.HANDLE),
    )


@dataclass(frozen=True, slots=True)
class _WindowsOwnerData:
    sid: str


class _WindowsHeldFileLock:
    def __init__(
        self,
        api: _WindowsAPI,
        handle: int,
        overlapped: _Overlapped,
    ) -> None:
        self._api = api
        self._handle = handle
        self._overlapped = overlapped

    def release(self) -> None:
        handle = self._handle
        if handle == _INVALID_HANDLE_VALUE:
            return
        self._handle = _INVALID_HANDLE_VALUE
        try:
            self._api.unlock_file(handle, self._overlapped)
        finally:
            self._api.close_handle(handle)


class _WindowsAPI:
    def __init__(self) -> None:
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise RuntimeError("Windows state backend requires a Windows interpreter")
        load = cast(Any, loader)
        self._kernel32: Any = load("kernel32", use_last_error=True)
        self._advapi32: Any = load("advapi32", use_last_error=True)
        self._shell32: Any = load("shell32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._kernel32.GetCurrentProcess.argtypes = ()
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
        self._kernel32.LocalFree.restype = wintypes.HLOCAL
        self._kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.GetFileInformationByHandleEx.argtypes = (
            wintypes.HANDLE,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self._kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self._kernel32.ReadFile.argtypes = (
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        )
        self._kernel32.ReadFile.restype = wintypes.BOOL
        self._kernel32.LockFileEx.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_Overlapped),
        )
        self._kernel32.LockFileEx.restype = wintypes.BOOL
        self._kernel32.UnlockFileEx.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_Overlapped),
        )
        self._kernel32.UnlockFileEx.restype = wintypes.BOOL

        self._advapi32.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        self._advapi32.OpenProcessToken.restype = wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi32.GetTokenInformation.restype = wintypes.BOOL
        self._advapi32.ConvertSidToStringSidW.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        )
        self._advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        self._advapi32.GetSecurityDescriptorDacl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        )
        self._advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        self._advapi32.SetNamedSecurityInfoW.argtypes = (
            wintypes.LPWSTR,
            wintypes.INT,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self._advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
        self._shell32.IsUserAnAdmin.argtypes = ()
        self._shell32.IsUserAnAdmin.restype = wintypes.BOOL

    def current_user_sid(self) -> str:
        token = wintypes.HANDLE()
        process = self._kernel32.GetCurrentProcess()
        if not self._advapi32.OpenProcessToken(
            process,
            _TOKEN_QUERY,
            ctypes.byref(token),
        ):
            self._raise_last_error("OpenProcessToken")
        try:
            size = wintypes.DWORD()
            self._advapi32.GetTokenInformation(
                token,
                _TOKEN_USER_CLASS,
                None,
                0,
                ctypes.byref(size),
            )
            if self._last_error() != _ERROR_INSUFFICIENT_BUFFER or size.value == 0:
                self._raise_last_error("GetTokenInformation")
            buffer = ctypes.create_string_buffer(size.value)
            if not self._advapi32.GetTokenInformation(
                token,
                _TOKEN_USER_CLASS,
                buffer,
                size,
                ctypes.byref(size),
            ):
                self._raise_last_error("GetTokenInformation")
            token_user = ctypes.cast(
                buffer,
                ctypes.POINTER(_TokenUser),
            ).contents
            string_sid = wintypes.LPWSTR()
            if not self._advapi32.ConvertSidToStringSidW(
                token_user.user.sid,
                ctypes.byref(string_sid),
            ):
                self._raise_last_error("ConvertSidToStringSidW")
            try:
                if string_sid.value is None:
                    raise RuntimeError("Windows returned an empty user SID")
                return string_sid.value
            finally:
                self._kernel32.LocalFree(string_sid)
        finally:
            self.close_handle(cast(int, token.value))

    def is_elevated(self) -> bool:
        return bool(self._shell32.IsUserAnAdmin())

    def protect_path(self, path: Path, sid: str) -> None:
        descriptor = ctypes.c_void_p()
        descriptor_size = wintypes.DWORD()
        sddl = f"D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        if not self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            _SDDL_REVISION_1,
            ctypes.byref(descriptor),
            ctypes.byref(descriptor_size),
        ):
            self._raise_last_error(
                "ConvertStringSecurityDescriptorToSecurityDescriptorW"
            )
        try:
            dacl_present = wintypes.BOOL()
            dacl = ctypes.c_void_p()
            dacl_defaulted = wintypes.BOOL()
            if not self._advapi32.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(dacl_present),
                ctypes.byref(dacl),
                ctypes.byref(dacl_defaulted),
            ):
                self._raise_last_error("GetSecurityDescriptorDacl")
            if not dacl_present.value or dacl.value is None:
                raise RuntimeError("Windows state security descriptor has no DACL")
            security_information = (
                _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION
            )
            mutable_path = ctypes.create_unicode_buffer(os.fspath(path))
            error_code = int(
                self._advapi32.SetNamedSecurityInfoW(
                    mutable_path,
                    _SE_FILE_OBJECT,
                    security_information,
                    None,
                    None,
                    dacl,
                    None,
                )
            )
            if error_code:
                self._raise_windows_error(
                    "SetNamedSecurityInfoW",
                    error_code,
                )
        finally:
            self._kernel32.LocalFree(descriptor)

    def read_file(self, path: Path) -> bytes:
        handle = self._open_regular_file(path, _GENERIC_READ, _OPEN_EXISTING)
        chunks: list[bytes] = []
        try:
            buffer = ctypes.create_string_buffer(64 * 1024)
            while True:
                count = wintypes.DWORD()
                if not self._kernel32.ReadFile(
                    handle,
                    buffer,
                    len(buffer),
                    ctypes.byref(count),
                    None,
                ):
                    self._raise_last_error("ReadFile")
                if count.value == 0:
                    break
                chunks.append(buffer.raw[: count.value])
        finally:
            self.close_handle(handle)
        return b"".join(chunks)

    def lock_file(
        self,
        path: Path,
        *,
        sid: str,
        exclusive: bool,
        deadline: float | None,
        timeout_message: str,
    ) -> _HeldFileLock:
        handle = self._open_regular_file(
            path,
            _GENERIC_READ | _GENERIC_WRITE,
            _OPEN_ALWAYS,
        )
        try:
            self.protect_path(path, sid)
            overlapped = _Overlapped()
            flags = _LOCKFILE_FAIL_IMMEDIATELY
            if exclusive:
                flags |= _LOCKFILE_EXCLUSIVE_LOCK
            while True:
                if self._kernel32.LockFileEx(
                    handle,
                    flags,
                    0,
                    1,
                    0,
                    ctypes.byref(overlapped),
                ):
                    return _WindowsHeldFileLock(self, handle, overlapped)
                error_code = self._last_error()
                if error_code not in {
                    _ERROR_LOCK_VIOLATION,
                    _ERROR_IO_PENDING,
                }:
                    self._raise_windows_error("LockFileEx", error_code)
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LockTimeoutError(timeout_message) from None
                    time.sleep(min(0.01, remaining))
                else:
                    time.sleep(0.01)
        except BaseException:
            self.close_handle(handle)
            raise

    def unlock_file(self, handle: int, overlapped: _Overlapped) -> None:
        if not self._kernel32.UnlockFileEx(
            handle,
            0,
            1,
            0,
            ctypes.byref(overlapped),
        ):
            self._raise_last_error("UnlockFileEx")

    def close_handle(self, handle: int) -> None:
        if handle in {0, _INVALID_HANDLE_VALUE}:
            return
        if not self._kernel32.CloseHandle(handle):
            self._raise_last_error("CloseHandle")

    def _open_regular_file(self, path: Path, access: int, creation: int) -> int:
        handle = cast(
            int,
            self._kernel32.CreateFileW(
                os.fspath(path),
                access,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                None,
                creation,
                _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            ),
        )
        if handle == _INVALID_HANDLE_VALUE:
            self._raise_last_error("CreateFileW")
        try:
            information = _FileAttributeTagInfo()
            if not self._kernel32.GetFileInformationByHandleEx(
                handle,
                _FILE_ATTRIBUTE_TAG_INFO_CLASS,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                self._raise_last_error("GetFileInformationByHandleEx")
            if information.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise StateCatalogError(f"state file cannot be a link: {path}")
            if information.file_attributes & _FILE_ATTRIBUTE_DIRECTORY:
                raise StateCatalogError(f"state path is not a regular file: {path}")
            return handle
        except BaseException:
            self.close_handle(handle)
            raise

    @staticmethod
    def _last_error() -> int:
        getter = cast(Any, ctypes.__dict__["get_last_error"])
        return int(getter())

    def _raise_last_error(self, operation: str) -> Never:
        self._raise_windows_error(operation, self._last_error())

    @staticmethod
    def _raise_windows_error(operation: str, error_code: int) -> Never:
        formatter = cast(Any, ctypes.__dict__["FormatError"])
        message = str(formatter(error_code)).strip()
        raise OSError(error_code, f"{operation} failed: {message}")


class _WindowsStatePlatform:
    name = "windows"

    def __init__(self) -> None:
        self._windows_api: _WindowsAPI | None = None

    @property
    def _api(self) -> _WindowsAPI:
        if self._windows_api is None:
            self._windows_api = _WindowsAPI()
        return self._windows_api

    def is_elevated(self) -> bool:
        return self._api.is_elevated()

    def resolve_owner(self, environment: Mapping[str, str]) -> _StateOwner:
        del environment
        sid = self._api.current_user_sid()
        return _StateOwner(
            self,
            f"windows:{sid}",
            Path.home().resolve(strict=False),
            self.is_elevated(),
            _WindowsOwnerData(sid),
        )

    def default_state_home(
        self,
        owner: _StateOwner,
        environment: Mapping[str, str],
    ) -> Path:
        _owner_data(owner)
        configured = environment.get("LOCALAPPDATA", "")
        base = Path(configured) if configured else owner.home / "AppData" / "Local"
        if not base.is_absolute():
            base = owner.home / "AppData" / "Local"
        return (base / "Engulf" / "State").resolve(strict=False)

    def is_link(self, path: Path) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return False
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT) or path.is_symlink()

    def ensure_directory(self, directory: Path, owner: _StateOwner) -> None:
        data = _owner_data(owner)
        missing: list[Path] = []
        current = directory
        while not os.path.lexists(current):
            missing.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        if os.path.lexists(current):
            self.require_directory(current)

        for path in reversed(missing):
            try:
                path.mkdir()
            except FileExistsError:
                self.require_directory(path)
                continue
            self._api.protect_path(path, data.sid)

        self.require_directory(directory)

    def require_directory(self, directory: Path) -> None:
        metadata = directory.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if (
            attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise StateCatalogError(f"state path is not a directory: {directory}")

    def read_bytes_no_follow(self, path: Path) -> bytes:
        return self._api.read_file(path)

    def atomic_write(self, path: Path, data: bytes, owner: _StateOwner) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.set_inheritable(descriptor, False)
            self._api.protect_path(temporary_path, _owner_data(owner).sid)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)

    def remove_path(self, path: Path) -> None:
        if not os.path.lexists(path):
            return
        if self.is_link(path):
            if path.is_junction():
                path.rmdir()
            else:
                path.unlink()
            return
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    def acquire_file_lock(
        self,
        path: Path,
        *,
        owner: _StateOwner,
        exclusive: bool,
        deadline: float | None,
        timeout_message: str,
    ) -> _HeldFileLock:
        self.ensure_directory(path.parent, owner)
        return self._api.lock_file(
            path,
            sid=_owner_data(owner).sid,
            exclusive=exclusive,
            deadline=deadline,
            timeout_message=timeout_message,
        )


def _owner_data(owner: _StateOwner) -> _WindowsOwnerData:
    data = owner.native
    if owner.platform is not WINDOWS_STATE_PLATFORM or not isinstance(
        data,
        _WindowsOwnerData,
    ):
        raise TypeError("state owner does not belong to the Windows backend")
    return data


WINDOWS_STATE_PLATFORM = _WindowsStatePlatform()
