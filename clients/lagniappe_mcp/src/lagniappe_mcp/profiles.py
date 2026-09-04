"""Owner-only connection profiles and race-safe local file replacement."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import ctypes
import errno
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterator, Mapping, TypeAlias

try:  # The first release advertises Linux only; keep unsupported hosts diagnosable.
    import fcntl
except ImportError:  # pragma: no cover - native Windows refusal
    fcntl = None  # type: ignore[assignment]

from .configuration import ConnectionConfig
from .errors import ConfigurationError
from .url_security import normalize_site_url


PROFILE_SCHEMA_VERSION = 1
PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONFIG_BYTES = 2 * 1024 * 1024
FileSnapshot: TypeAlias = tuple[bytes, os.stat_result]
_UNSPECIFIED_SNAPSHOT = object()
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
_RENAMEAT2_SYSCALLS = {
    "aarch64": 276,
    "amd64": 316,
    "x86_64": 316,
}


class _AtomicRenameUnavailable(OSError):
    """The host cannot provide a required kernel-enforced rename operation."""


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::load_profile
def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::load_profile
def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::load_profile
def _finite_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::save_profile
def validate_profile_name(value: str) -> str:
    name = str(value or "")
    if not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(
            "invalid_profile",
            "Profile names must match [a-z][a-z0-9-]{0,31}.",
        )
    return name


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::profile_path
def _config_base(environ: Mapping[str, str]) -> Path:
    override = environ.get("LAGNIAPPE_MCP_CONFIG_HOME")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            raise ConfigurationError(
                "unsafe_path",
                "LAGNIAPPE_MCP_CONFIG_HOME must be an absolute user path.",
            )
        return candidate
    xdg = environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidate = Path(xdg).expanduser()
        if not candidate.is_absolute():
            raise ConfigurationError(
                "unsafe_path", "XDG_CONFIG_HOME must be an absolute user path."
            )
        return candidate / "lagniappe-mcp"
    home_value = environ.get("HOME")
    home = Path(home_value).expanduser() if home_value else Path.home()
    if not home.is_absolute():
        raise ConfigurationError(
            "unsafe_path", "HOME must resolve to an absolute user path."
        )
    return home / ".config" / "lagniappe-mcp"


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_paths_never_anchor_relative_config_roots_to_the_working_directory
def profile_path(name: str, *, environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    return _config_base(values) / "profiles" / f"{validate_profile_name(name)}.json"


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _absolute(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if any(part == ".." for part in candidate.parts):
        raise ConfigurationError(
            "unsafe_path",
            "Configuration paths cannot contain parent traversal.",
        )
    return candidate


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _open_directory(path: Path, *, create: bool, private_tail: int = 0) -> int:
    """Open an absolute directory one no-follow component at a time."""
    if os.name != "posix" or fcntl is None:
        raise ConfigurationError(
            "unsupported_platform",
            "This release supports secure profiles on POSIX only.",
        )
    absolute = _absolute(path)
    parts = absolute.parts
    if not parts or parts[0] != os.sep:
        raise ConfigurationError(
            "unsafe_path", "Configuration directory must be absolute."
        )
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(parts[1:], start=1):
            private_component = index > len(parts) - 1 - private_tail
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
            except FileNotFoundError:
                if not create:
                    raise ConfigurationError(
                        "profile_not_found", "The requested profile does not exist."
                    ) from None
                mode = 0o700 if private_component else 0o755
                try:
                    os.mkdir(part, mode=mode, dir_fd=fd)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise ConfigurationError(
                        "unsafe_path",
                        "Configuration path could not be created safely.",
                    ) from error
                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=fd,
                    )
                except OSError as error:
                    raise ConfigurationError(
                        "unsafe_path",
                        "Configuration path contains an unsafe component.",
                    ) from error
            except OSError as error:
                raise ConfigurationError(
                    "unsafe_path", "Configuration path contains an unsafe component."
                ) from error
            details = os.fstat(next_fd)
            if private_component and (
                details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077
            ):
                os.close(next_fd)
                raise ConfigurationError(
                    "unsafe_permissions",
                    "Private configuration directories must be owner-only.",
                )
            os.close(fd)
            fd = next_fd
        details = os.fstat(fd)
        if details.st_uid != os.getuid():
            raise ConfigurationError(
                "unsafe_path",
                "Configuration directory is not owned by the current user.",
            )
        if not private_tail and stat.S_IMODE(details.st_mode) & 0o022:
            raise ConfigurationError(
                "unsafe_permissions",
                "Configuration directory must not be group- or world-writable.",
            )
        return fd
    except Exception:
        os.close(fd)
        raise


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _read_at(
    directory_fd: int, filename: str, *, private: bool
) -> tuple[bytes, os.stat_result] | None:
    try:
        fd = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ConfigurationError(
            "unsafe_file", "Configuration target is unsafe."
        ) from error
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            raise ConfigurationError(
                "unsafe_file", "Configuration target must be an owned regular file."
            )
        if private and stat.S_IMODE(details.st_mode) & 0o077:
            raise ConfigurationError(
                "unsafe_permissions",
                "Credential profile permissions are not owner-only.",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_CONFIG_BYTES:
                raise ConfigurationError(
                    "config_too_large",
                    "Configuration file exceeds the local safety limit.",
                )
        return b"".join(chunks), details
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(
            "read_failed", "Configuration data could not be read safely."
        ) from error
    finally:
        os.close(fd)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
@contextmanager
def _locked(directory_fd: int, filename: str) -> Iterator[None]:
    lock_name = f".{filename}.lagniappe-mcp.lock"
    try:
        fd = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as error:
        raise ConfigurationError(
            "lock_failed", "Could not acquire the configuration lock."
        ) from error
    try:
        try:
            details = os.fstat(fd)
            if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
                raise ConfigurationError("unsafe_file", "Configuration lock is unsafe.")
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except ConfigurationError:
            raise
        except OSError as error:
            raise ConfigurationError(
                "lock_failed", "Could not acquire the configuration lock."
            ) from error
        yield
    finally:
        os.close(fd)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _snapshot_matches(
    directory_fd: int,
    filename: str,
    original: tuple[bytes, os.stat_result] | None,
    *,
    private: bool,
) -> bool:
    current = _read_at(directory_fd, filename, private=private)
    return _same_snapshot(original, current)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _same_snapshot(
    original: FileSnapshot | None,
    current: FileSnapshot | None,
) -> bool:
    """Compare the bytes and identity metadata captured by one safe read."""
    if original is None or current is None:
        return original is current
    old_bytes, old_stat = original
    new_bytes, new_stat = current
    return (
        old_bytes == new_bytes
        and old_stat.st_dev == new_stat.st_dev
        and old_stat.st_ino == new_stat.st_ino
        and old_stat.st_uid == new_stat.st_uid
        and old_stat.st_gid == new_stat.st_gid
        and old_stat.st_size == new_stat.st_size
        and old_stat.st_nlink == new_stat.st_nlink
        and old_stat.st_mtime_ns == new_stat.st_mtime_ns
        and old_stat.st_ctime_ns == new_stat.st_ctime_ns
        and old_stat.st_mode == new_stat.st_mode
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _same_displaced_snapshot(
    original: FileSnapshot,
    moved: FileSnapshot | None,
) -> bool:
    """Compare after rename, which legitimately advances the inode ctime."""
    if moved is None:
        return False
    old_bytes, old_stat = original
    new_bytes, new_stat = moved
    return (
        old_bytes == new_bytes
        and old_stat.st_dev == new_stat.st_dev
        and old_stat.st_ino == new_stat.st_ino
        and old_stat.st_uid == new_stat.st_uid
        and old_stat.st_gid == new_stat.st_gid
        and old_stat.st_size == new_stat.st_size
        and old_stat.st_nlink == new_stat.st_nlink
        and old_stat.st_mtime_ns == new_stat.st_mtime_ns
        and old_stat.st_mode == new_stat.st_mode
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _rename_with_flags(
    directory_fd: int,
    source: str,
    destination: str,
    *,
    flags: int,
) -> None:
    """Use one Linux renameat2 operation relative to a held directory."""
    if platform.system() != "Linux":
        raise _AtomicRenameUnavailable(
            errno.ENOSYS, "renameat2 is unavailable on this platform"
        )
    machine = platform.machine().lower()
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            directory_fd,
            source_bytes,
            directory_fd,
            destination_bytes,
            flags,
        )
    else:
        syscall_number = _RENAMEAT2_SYSCALLS.get(machine)
        if syscall_number is None:
            raise _AtomicRenameUnavailable(
                errno.ENOSYS, "renameat2 is unavailable on this platform"
            )
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        result = syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_int(directory_fd),
            ctypes.c_char_p(source_bytes),
            ctypes.c_int(directory_fd),
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(flags),
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise _AtomicRenameUnavailable(
            error_number,
            "the required renameat2 operation is unavailable",
        )
    if flags == _RENAME_NOREPLACE and error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    if error_number == errno.ENOENT:
        raise FileNotFoundError(error_number, os.strerror(error_number), source)
    raise OSError(error_number, os.strerror(error_number), source)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _rename_noreplace(directory_fd: int, source: str, destination: str) -> None:
    """Rename without replacing an existing destination."""
    _rename_with_flags(
        directory_fd,
        source,
        destination,
        flags=_RENAME_NOREPLACE,
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _rename_exchange(directory_fd: int, source: str, destination: str) -> None:
    """Atomically exchange two existing directory entries."""
    _rename_with_flags(
        directory_fd,
        source,
        destination,
        flags=_RENAME_EXCHANGE,
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _atomic_update_unavailable(*, private: bool) -> ConfigurationError:
    if private:
        return ConfigurationError(
            "atomic_update_unsupported",
            "This filesystem cannot safely update saved credentials; use --from-env.",
        )
    return ConfigurationError(
        "manual_configuration_required",
        "Codex configuration cannot be changed without a no-clobber rename; "
        "use the printed manual block.",
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _recovery_name(filename: str) -> str:
    return f".{filename}.{os.getpid()}.{secrets.token_hex(8)}.recover"


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _restore_displaced(
    directory_fd: int,
    displaced: str,
    filename: str,
    *,
    private: bool,
) -> None:
    """Restore a displaced target without overwriting a newer pathname."""
    try:
        _rename_noreplace(directory_fd, displaced, filename)
        os.fsync(directory_fd)
    except FileExistsError as error:
        raise ConfigurationError(
            "configuration_recovery_required",
            "Concurrent edits were preserved, but configuration recovery is required.",
        ) from error
    except _AtomicRenameUnavailable as error:
        raise _atomic_update_unavailable(private=private) from error
    except OSError as error:
        raise ConfigurationError(
            "configuration_recovery_required",
            "Configuration could not be restored after a concurrent change.",
        ) from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _displace_matching_target(
    directory_fd: int,
    filename: str,
    original: FileSnapshot,
    *,
    private: bool,
) -> str:
    """Move the live name aside, then prove the moved inode is the reviewed one."""
    displaced = _recovery_name(filename)
    try:
        _rename_noreplace(directory_fd, filename, displaced)
    except FileNotFoundError as error:
        raise ConfigurationError(
            "concurrent_change", "Configuration changed before it could be saved."
        ) from error
    except _AtomicRenameUnavailable as error:
        raise _atomic_update_unavailable(private=private) from error
    except OSError as error:
        raise ConfigurationError(
            "save_failed", "Configuration target could not be claimed safely."
        ) from error

    try:
        moved = _read_at(directory_fd, displaced, private=private)
    except ConfigurationError as error:
        try:
            _restore_displaced(
                directory_fd,
                displaced,
                filename,
                private=private,
            )
        except ConfigurationError as restore_error:
            raise restore_error from error
        raise ConfigurationError(
            "concurrent_change", "Configuration changed before it could be saved."
        ) from error
    if _same_displaced_snapshot(original, moved):
        return displaced
    try:
        _restore_displaced(
            directory_fd,
            displaced,
            filename,
            private=private,
        )
    except ConfigurationError as restore_error:
        raise restore_error
    raise ConfigurationError(
        "concurrent_change", "Configuration changed before it could be saved."
    )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _stage_at(
    directory_fd: int,
    filename: str,
    data: bytes,
    *,
    mode: int,
) -> str:
    """Durably stage owner-controlled bytes in the destination directory."""
    temporary = f".{filename}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=directory_fd,
        )
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise ConfigurationError(
                        "save_failed",
                        "Configuration data could not be written completely.",
                    )
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        return temporary
    except ConfigurationError:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    except OSError as error:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        raise ConfigurationError(
            "save_failed", "Configuration data could not be staged safely."
        ) from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _cleanup_private_transactions(directory_fd: int, filename: str) -> None:
    """Remove abandoned owner-only stages while the target lock is held."""
    transaction_pattern = re.compile(
        rf"^\.{re.escape(filename)}\.[0-9]+\.[0-9a-f]{{16}}\.(?:tmp|recover)$"
    )
    try:
        entries = os.listdir(directory_fd)
    except OSError as error:
        raise ConfigurationError(
            "read_failed", "Private configuration transactions could not be listed."
        ) from error

    removed = False
    for entry in entries:
        if not transaction_pattern.fullmatch(entry):
            continue
        try:
            fd = os.open(
                entry,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ConfigurationError(
                "unsafe_file", "Private configuration transaction is unsafe."
            ) from error
        try:
            details = os.fstat(fd)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or details.st_nlink != 1
                or stat.S_IMODE(details.st_mode) & 0o077
            ):
                raise ConfigurationError(
                    "unsafe_file", "Private configuration transaction is unsafe."
                )
        finally:
            os.close(fd)
        try:
            os.unlink(entry, dir_fd=directory_fd)
            removed = True
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ConfigurationError(
                "configuration_recovery_required",
                "Abandoned credential transaction could not be removed safely.",
            ) from error
    if removed:
        try:
            os.fsync(directory_fd)
        except OSError as error:
            raise ConfigurationError(
                "configuration_recovery_required",
                "Credential transaction cleanup could not be made durable.",
            ) from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _after_private_replace(_directory_fd: int, _filename: str) -> None:
    """Fault-injection seam after a credential pathname replacement."""


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_delete
def _after_private_delete(_directory_fd: int, _filename: str) -> None:
    """Fault-injection seam after a credential pathname removal."""


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _after_exchange(_directory_fd: int, _temporary: str, _filename: str) -> None:
    """Fault-injection seam immediately after an atomic pathname exchange."""


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _preserve_exchange_recovery(
    directory_fd: int,
    temporary: str,
    filename: str,
) -> None:
    recovery = _recovery_name(filename)
    try:
        _rename_noreplace(directory_fd, temporary, recovery)
        os.fsync(directory_fd)
    except OSError:
        # The exchange temporary already remains private in the same directory.
        pass


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _rollback_exchange(
    directory_fd: int,
    temporary: str,
    filename: str,
    staged: FileSnapshot,
    *,
    private: bool,
) -> None:
    """Exchange back without ever making the canonical pathname disappear."""
    try:
        canonical = _read_at(directory_fd, filename, private=private)
    except ConfigurationError as error:
        _preserve_exchange_recovery(directory_fd, temporary, filename)
        raise ConfigurationError(
            "configuration_recovery_required",
            "A newer configuration revision was preserved; recovery is required.",
        ) from error
    if not _same_displaced_snapshot(staged, canonical):
        # A non-cooperating writer changed the canonical name after our first
        # exchange.  Never exchange blindly here: doing so would hide that
        # newer revision under a private recovery name and restore stale data.
        _preserve_exchange_recovery(directory_fd, temporary, filename)
        raise ConfigurationError(
            "configuration_recovery_required",
            "A newer configuration revision was preserved; recovery is required.",
        )
    try:
        _rename_exchange(directory_fd, temporary, filename)
        os.fsync(directory_fd)
    except _AtomicRenameUnavailable as error:
        raise _atomic_update_unavailable(private=private) from error
    except OSError as error:
        raise ConfigurationError(
            "configuration_recovery_required",
            "Configuration remained present, but its atomic rollback failed.",
        ) from error
    try:
        returned = _read_at(directory_fd, temporary, private=True)
    except ConfigurationError as error:
        _preserve_exchange_recovery(directory_fd, temporary, filename)
        raise ConfigurationError(
            "configuration_recovery_required",
            "Concurrent edits were preserved, but configuration recovery is required.",
        ) from error
    if not _same_displaced_snapshot(staged, returned):
        _preserve_exchange_recovery(directory_fd, temporary, filename)
        raise ConfigurationError(
            "configuration_recovery_required",
            "Concurrent edits were preserved, but configuration recovery is required.",
        )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::atomic_write
def _write_at(
    directory_fd: int,
    filename: str,
    data: bytes,
    *,
    mode: int,
    original: tuple[bytes, os.stat_result] | None,
    private: bool,
    credential: bool,
    prepared: str | None = None,
) -> FileSnapshot:
    temporary = prepared or _stage_at(directory_fd, filename, data, mode=mode)
    temporary_safe_to_remove = True
    try:
        staged = _read_at(directory_fd, temporary, private=False)
        if (
            staged is None
            or staged[0] != data
            or stat.S_IMODE(staged[1].st_mode) != mode
        ):
            raise ConfigurationError(
                "save_failed", "Staged configuration data could not be verified."
            )
        # Compare after the potentially slow write/fsync and immediately before
        # the atomic replacement. Cooperating writers also hold the target lock.
        if not _snapshot_matches(directory_fd, filename, original, private=private):
            raise ConfigurationError(
                "concurrent_change", "Configuration changed before it could be saved."
            )
        if original is None:
            try:
                _rename_noreplace(directory_fd, temporary, filename)
            except FileExistsError as error:
                raise ConfigurationError(
                    "concurrent_change",
                    "Configuration changed before it could be saved.",
                ) from error
            except _AtomicRenameUnavailable as error:
                raise _atomic_update_unavailable(private=private) from error
            os.fsync(directory_fd)
            saved = _read_at(directory_fd, filename, private=private)
            if not _same_displaced_snapshot(staged, saved):
                raise ConfigurationError(
                    "save_failed", "Configuration replacement could not be verified."
                )
            return saved

        if credential:
            # All adapter writers for this profile hold the target lock, and
            # the full snapshot was checked immediately above. POSIX has no
            # operation that both conditionally replaces a particular inode
            # and leaves no name for the displaced credential. A direct
            # atomic replacement therefore provides the stronger credential
            # invariant: after commit (including an abrupt process exit), the
            # old key has no adapter-created pathname. Same-user writers that
            # ignore the lock cannot be given lock-free CAS semantics.
            try:
                os.replace(
                    temporary,
                    filename,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except OSError as error:
                raise ConfigurationError(
                    "save_failed", "Credential profile could not be replaced safely."
                ) from error
            os.fsync(directory_fd)
            _after_private_replace(directory_fd, filename)
            saved = _read_at(directory_fd, filename, private=True)
            if not _same_displaced_snapshot(staged, saved):
                # Never attempt a rollback here: a same-user writer that did
                # not honor the lock may have installed a newer canonical
                # revision after our replacement.
                raise ConfigurationError(
                    "concurrent_change",
                    "Credential profile changed during replacement; newer bytes "
                    "were preserved.",
                )
            return saved

        try:
            _rename_exchange(directory_fd, temporary, filename)
        except FileNotFoundError as error:
            raise ConfigurationError(
                "concurrent_change", "Configuration changed before it could be saved."
            ) from error
        except _AtomicRenameUnavailable as error:
            raise _atomic_update_unavailable(private=private) from error
        temporary_safe_to_remove = False
        os.fsync(directory_fd)
        _after_exchange(directory_fd, temporary, filename)

        try:
            displaced = _read_at(directory_fd, temporary, private=private)
        except ConfigurationError as error:
            _rollback_exchange(
                directory_fd,
                temporary,
                filename,
                staged,
                private=private,
            )
            temporary_safe_to_remove = True
            raise ConfigurationError(
                "concurrent_change", "Configuration changed during replacement."
            ) from error
        if not _same_displaced_snapshot(original, displaced):
            _rollback_exchange(
                directory_fd,
                temporary,
                filename,
                staged,
                private=private,
            )
            temporary_safe_to_remove = True
            raise ConfigurationError(
                "concurrent_change", "Configuration changed during replacement."
            )

        try:
            saved = _read_at(directory_fd, filename, private=private)
        except ConfigurationError as error:
            _preserve_exchange_recovery(directory_fd, temporary, filename)
            raise ConfigurationError(
                "configuration_recovery_required",
                "A newer configuration revision was preserved; recovery is required.",
            ) from error
        if not _same_displaced_snapshot(staged, saved):
            _preserve_exchange_recovery(directory_fd, temporary, filename)
            raise ConfigurationError(
                "configuration_recovery_required",
                "A newer configuration revision was preserved; recovery is required.",
            )

        os.unlink(temporary, dir_fd=directory_fd)
        temporary_safe_to_remove = True
        os.fsync(directory_fd)
        return saved
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(
            "save_failed", "Configuration data could not be saved safely."
        ) from error
    finally:
        if temporary_safe_to_remove:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_atomic_write_detects_race_after_temp_fsync
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_install_is_lossless_backed_up_and_idempotent
def atomic_write(
    path: Path,
    data: bytes,
    *,
    private: bool,
    backup: bool = False,
    expected_snapshot: FileSnapshot | None | object = _UNSPECIFIED_SNAPSHOT,
) -> None:
    directory_fd = _open_directory(
        path.parent, create=True, private_tail=2 if private else 0
    )
    backup_temporary: str | None = None
    try:
        backup_name = f"{path.name}.lagniappe-mcp.bak" if backup else None
        with ExitStack() as locks:
            locks.enter_context(_locked(directory_fd, path.name))
            if backup_name is not None:
                locks.enter_context(_locked(directory_fd, backup_name))
            if private:
                _cleanup_private_transactions(directory_fd, path.name)
            original = _read_at(directory_fd, path.name, private=private)
            if expected_snapshot is not _UNSPECIFIED_SNAPSHOT and not _same_snapshot(
                expected_snapshot, original
            ):
                raise ConfigurationError(
                    "concurrent_change",
                    "Configuration changed after it was reviewed.",
                )
            if (
                original is not None
                and original[0] == data
                and stat.S_IMODE(original[1].st_mode) == 0o600
            ):
                return
            backup_original: FileSnapshot | None = None
            if backup_name is not None and original is not None:
                backup_original = _read_at(directory_fd, backup_name, private=True)
                # Stage and fsync the protected pre-mutation revision before
                # changing the main name, while leaving the prior fixed backup
                # untouched until that main compare-and-swap succeeds.
                backup_temporary = _stage_at(
                    directory_fd,
                    backup_name,
                    original[0],
                    mode=0o600,
                )
            committed_snapshot = _write_at(
                directory_fd,
                path.name,
                data,
                mode=0o600,
                original=original,
                private=private,
                credential=private,
            )
            # The fixed backup name is updated only after the main CAS commits.
            # A rejected main mutation must not rewrite a valid older backup.
            if backup_name is not None and original is not None:
                prepared_backup = backup_temporary
                backup_temporary = None
                try:
                    _write_at(
                        directory_fd,
                        backup_name,
                        original[0],
                        mode=0o600,
                        original=backup_original,
                        private=True,
                        credential=False,
                        prepared=prepared_backup,
                    )
                except BaseException as backup_error:
                    # The main update cannot remain committed when its promised
                    # protected backup was not. Restore reviewed bytes through
                    # the same no-clobber CAS; a newer edit is never replaced.
                    replacement = _read_at(
                        directory_fd,
                        path.name,
                        private=private,
                    )
                    if not _same_snapshot(committed_snapshot, replacement):
                        if prepared_backup is not None:
                            _preserve_exchange_recovery(
                                directory_fd,
                                prepared_backup,
                                backup_name,
                            )
                        raise ConfigurationError(
                            "configuration_rollback_failed",
                            "Codex configuration changed while its backup failed; "
                            "newer bytes were preserved.",
                        ) from backup_error
                    try:
                        _write_at(
                            directory_fd,
                            path.name,
                            original[0],
                            mode=stat.S_IMODE(original[1].st_mode),
                            original=replacement,
                            private=private,
                            credential=False,
                        )
                    except BaseException as rollback_error:
                        if prepared_backup is not None:
                            _preserve_exchange_recovery(
                                directory_fd,
                                prepared_backup,
                                backup_name,
                            )
                        raise ConfigurationError(
                            "configuration_rollback_failed",
                            "Codex configuration could not be restored after "
                            "its backup failed.",
                        ) from rollback_error
                    if prepared_backup is not None:
                        try:
                            residue = _read_at(
                                directory_fd,
                                prepared_backup,
                                private=True,
                            )
                        except ConfigurationError:
                            residue = None
                        if (
                            residue is not None
                            and residue[0] == original[0]
                            and stat.S_IMODE(residue[1].st_mode) == 0o600
                        ):
                            os.unlink(prepared_backup, dir_fd=directory_fd)
                            os.fsync(directory_fd)
                        elif residue is not None:
                            _preserve_exchange_recovery(
                                directory_fd,
                                prepared_backup,
                                backup_name,
                            )
                    raise backup_error
    finally:
        if backup_temporary is not None:
            try:
                os.unlink(backup_temporary, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_codex_install_is_lossless_backed_up_and_idempotent
def secure_read(path: Path, *, private: bool) -> bytes | None:
    """Read one owned regular file without following its final path component."""
    loaded = secure_read_snapshot(path, private=private)
    return None if loaded is None else loaded[0]


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::secure_read
def secure_read_snapshot(path: Path, *, private: bool) -> FileSnapshot | None:
    """Read bytes together with the identity metadata required for later CAS."""
    directory_fd = _open_directory(
        path.parent, create=False, private_tail=2 if private else 0
    )
    try:
        with _locked(directory_fd, path.name):
            if private:
                _cleanup_private_transactions(directory_fd, path.name)
            return _read_at(directory_fd, path.name, private=private)
    finally:
        os.close(directory_fd)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def atomic_delete(
    path: Path,
    *,
    private: bool,
    expected_snapshot: FileSnapshot | object = _UNSPECIFIED_SNAPSHOT,
) -> None:
    directory_fd = _open_directory(
        path.parent, create=False, private_tail=2 if private else 0
    )
    try:
        with _locked(directory_fd, path.name):
            if private:
                _cleanup_private_transactions(directory_fd, path.name)
            original = _read_at(directory_fd, path.name, private=private)
            if original is None:
                raise ConfigurationError(
                    "profile_not_found", "The requested profile does not exist."
                )
            if expected_snapshot is not _UNSPECIFIED_SNAPSHOT and not _same_snapshot(
                expected_snapshot, original
            ):
                raise ConfigurationError(
                    "concurrent_change",
                    "Configuration changed after it was reviewed.",
                )
            if not _snapshot_matches(
                directory_fd, path.name, original, private=private
            ):
                raise ConfigurationError(
                    "concurrent_change", "Configuration changed before removal."
                )
            if private:
                # Unlink the canonical name directly so an interrupted delete
                # cannot strand the old credential under a recovery name.
                # Cooperating writers are serialized by the target lock; the
                # snapshot check above is deliberately immediately adjacent.
                try:
                    os.unlink(path.name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except FileNotFoundError as error:
                    raise ConfigurationError(
                        "concurrent_change",
                        "Configuration changed before removal.",
                    ) from error
                except OSError as error:
                    raise ConfigurationError(
                        "delete_failed", "Configuration could not be removed safely."
                    ) from error
                _after_private_delete(directory_fd, path.name)
                if _read_at(directory_fd, path.name, private=True) is not None:
                    raise ConfigurationError(
                        "concurrent_change",
                        "Credential profile changed during removal; newer bytes "
                        "were preserved.",
                    )
                return
            displaced = _displace_matching_target(
                directory_fd,
                path.name,
                original,
                private=private,
            )
            try:
                os.unlink(displaced, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except OSError as error:
                try:
                    _restore_displaced(
                        directory_fd,
                        displaced,
                        path.name,
                        private=private,
                    )
                except ConfigurationError as restore_error:
                    raise restore_error from error
                raise ConfigurationError(
                    "delete_failed", "Configuration could not be removed safely."
                ) from error
    finally:
        os.close(directory_fd)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def load_profile(
    name: str, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    value, _snapshot = load_profile_snapshot(name, environ=environ)
    return value


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::load_profile
def load_profile_snapshot(
    name: str, *, environ: Mapping[str, str] | None = None
) -> tuple[dict[str, Any], FileSnapshot]:
    """Load one profile and retain the exact revision used for later mutation."""
    path = profile_path(name, environ=environ)
    directory_fd = _open_directory(path.parent, create=False, private_tail=2)
    try:
        with _locked(directory_fd, path.name):
            _cleanup_private_transactions(directory_fd, path.name)
            loaded = _read_at(directory_fd, path.name, private=True)
    finally:
        os.close(directory_fd)
    if loaded is None:
        raise ConfigurationError(
            "profile_not_found", "The requested profile does not exist."
        )
    try:
        value = json.loads(
            loaded[0],
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise ConfigurationError(
            "invalid_profile", "The saved profile is malformed."
        ) from error
    _validate_profile(value, expected_name=name)
    return value, loaded


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/profiles.py::save_profile
def _validate_profile(value: object, *, expected_name: str | None = None) -> None:
    required = {
        "schema_version",
        "name",
        "site_url",
        "api_key",
        "allowed_roots",
        "actor",
        "credential",
        "client",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ConfigurationError(
            "invalid_profile", "The saved profile shape is incompatible."
        )
    name = validate_profile_name(value.get("name", ""))
    if (
        isinstance(value["schema_version"], bool)
        or value["schema_version"] != PROFILE_SCHEMA_VERSION
        or (expected_name is not None and name != validate_profile_name(expected_name))
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved profile identity is incompatible."
        )
    if value["api_key"] is not None and (
        not isinstance(value["api_key"], str) or not value["api_key"]
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved credential value is malformed."
        )
    roots = value["allowed_roots"]
    if (
        not isinstance(roots, list)
        or any(
            not isinstance(item, str)
            or not item
            or not Path(item).is_absolute()
            or ".." in Path(item).parts
            for item in roots
        )
        or len(set(roots)) != len(roots)
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved allowed roots are malformed."
        )
    if not isinstance(value["site_url"], str):
        raise ConfigurationError("invalid_profile", "The saved site URL is malformed.")
    if normalize_site_url(value["site_url"]).origin != value["site_url"]:
        raise ConfigurationError(
            "invalid_profile", "The saved site URL is not canonical."
        )

    actor = value["actor"]
    if (
        not isinstance(actor, dict)
        or set(actor) != {"name", "hash"}
        or any(
            not isinstance(actor.get(field), str) or not actor[field]
            for field in ("name", "hash")
        )
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved actor metadata is malformed."
        )
    credential = value["credential"]
    if (
        not isinstance(credential, dict)
        or (value["api_key"] is None) != (not credential)
        or (
            credential
            and (
                set(credential) != {"expires_at", "display_prefix", "generation"}
                or not isinstance(credential.get("expires_at"), str)
                or not credential["expires_at"]
                or credential.get("display_prefix") is not None
                and not isinstance(credential.get("display_prefix"), str)
                or credential.get("generation") is not None
                and (
                    isinstance(credential.get("generation"), bool)
                    or not isinstance(credential.get("generation"), int)
                )
            )
        )
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved credential metadata is malformed."
        )

    client = value["client"]
    if (
        not isinstance(client, dict)
        or set(client)
        != {
            "name",
            "mode",
            "registered",
            "fingerprint",
            "executable",
            "required",
        }
        or client.get("name") != f"lagniappe-{name}"
        or client.get("mode") not in {"automatic", "manual"}
        or not isinstance(client.get("registered"), bool)
        or not isinstance(client.get("executable"), str)
        or not Path(client["executable"]).is_absolute()
        or not isinstance(client.get("required"), bool)
        or (
            client.get("fingerprint") is not None
            and (
                not isinstance(client.get("fingerprint"), str)
                or not _FINGERPRINT_PATTERN.fullmatch(client["fingerprint"])
            )
        )
        or client.get("registered") is True
        and client.get("fingerprint") is None
    ):
        raise ConfigurationError(
            "invalid_profile", "The saved client ownership metadata is malformed."
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_write_rejects_shared_private_directories
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def save_profile(
    value: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    expected_snapshot: FileSnapshot | None | object = _UNSPECIFIED_SNAPSHOT,
) -> None:
    name = validate_profile_name(value.get("name", ""))
    _validate_profile(value, expected_name=name)
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    atomic_write(
        profile_path(name, environ=environ),
        payload,
        private=True,
        expected_snapshot=expected_snapshot,
    )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def delete_profile(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    expected_snapshot: FileSnapshot | object = _UNSPECIFIED_SNAPSHOT,
) -> None:
    atomic_delete(
        profile_path(name, environ=environ),
        private=True,
        expected_snapshot=expected_snapshot,
    )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def connection_from_profile(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> ConnectionConfig:
    value = load_profile(name, environ=environ)
    if not isinstance(value["api_key"], str) or not value["api_key"]:
        raise ConfigurationError(
            "missing_credentials", "The saved profile has no API key."
        )
    actor = value["actor"] if isinstance(value["actor"], dict) else {}
    return ConnectionConfig(
        authority=normalize_site_url(value["site_url"]),
        api_key=value["api_key"],
        allowed_roots=tuple(Path(item) for item in value["allowed_roots"]),
        profile_name=value["name"],
        actor_hash=actor.get("hash") if isinstance(actor.get("hash"), str) else None,
    )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_profile_round_trip_is_strict_and_owner_only
def profile_fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
