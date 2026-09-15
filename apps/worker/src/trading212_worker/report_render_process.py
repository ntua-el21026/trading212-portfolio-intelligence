"""One bounded renderer child; the parent retains source authorization and DB I/O."""

from __future__ import annotations

import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import suppress
from itertools import islice
from multiprocessing.connection import Connection
from pathlib import Path

from trading212_application import reports as app
from trading212_domain.report_manifest import (
    decode_report_chunk,
    decode_report_manifest,
    decode_report_manifest_v3,
    encode_report_manifest,
)
from trading212_domain.report_v3 import ReportManifestContract
from trading212_domain.reports import (
    ReportChunk,
    ReportFailureCode,
    ReportFormat,
    ReportTableKey,
    report_profile_version,
    report_schema_version,
)


class _ChildGuard:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def check(self) -> None:
        self._connection.send(("check",))
        if self._connection.recv() is not True:
            raise app.ReportRenderError(ReportFailureCode.LEASE_EXPIRED)


class _PipeDocument:
    def __init__(self, connection: Connection, manifest: ReportManifestContract) -> None:
        self._connection = connection
        self.manifest = manifest
        self.header = manifest.document

    def iter_chunks(self, table: ReportTableKey) -> Iterator[ReportChunk]:
        self._connection.send(("start", table.value))
        ordinal = 0
        while True:
            self._connection.send(("next", table.value, ordinal))
            value = self._connection.recv()
            if value is None:
                return
            if type(value) is not bytes or len(value) > 1024 * 1024:
                raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
            chunk = decode_report_chunk(value)
            if chunk.table is not table or chunk.ordinal != ordinal:
                raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
            yield chunk
            ordinal += 1


def _decode_manifest(payload: bytes, profile: str) -> ReportManifestContract:
    # The authorized parent supplies the profile separately; private JSON cannot
    # choose its decoder or turn an earlier report/export into a V3 document.
    if profile not in {"1", "2", "3"}:
        raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    manifest: ReportManifestContract = (
        decode_report_manifest_v3(payload) if profile == "3" else decode_report_manifest(payload)
    )
    if (
        manifest.document.document_schema_version != f"{profile}.0.0"
        or report_schema_version(manifest.document.selection) != f"{profile}.0.0"
        or report_profile_version(manifest.document.selection) != f"report_sections_v{profile}"
    ):
        raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    return manifest


def _child(
    connection: Connection, payload: bytes, format_value: str, scratch: str, profile: str
) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        from .report_renderers import BoundedArtifactBuffer, PrivateReportRenderer

        tempfile.tempdir = scratch
        manifest = _decode_manifest(payload, profile)
        document = _PipeDocument(connection, manifest)
        guard = _ChildGuard(connection)
        with BoundedArtifactBuffer(guard=guard) as buffer:
            receipt = PrivateReportRenderer().render(
                document,
                format=ReportFormat(format_value),
                profile=manifest.renderer_profile,
                sink=buffer,
                guard=guard,
            )
            connection.send(("done", buffer.finish(receipt)))
    except app.ReportRenderError as error:
        connection.send(("failed", error.code.value))
    except MemoryError:
        connection.send(("failed", ReportFailureCode.LIMIT_EXCEEDED.value))
    except BaseException:
        # A private child never propagates provider text, tracebacks or credentials.
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send(("failed", ReportFailureCode.RENDER_FAILED.value))
    finally:
        connection.close()


def _process_identity(pid: int) -> str | None:
    try:
        # comm may contain spaces or parentheses; field 22 is relative to its close.
        value = Path(f"/proc/{pid}/stat").read_text()
        return value[value.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        return None


def _workspace() -> tempfile.TemporaryDirectory[str]:
    root = Path(tempfile.gettempdir()) / f"t212pi-report-render-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if root.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED)
    # Recovery examines at most twenty private workspaces. A live PID/start-time
    # pair owns the directory even if that process has not written any artifacts.
    with os.scandir(root) as entries:
        for entry in islice(entries, 20):
            if not entry.name.startswith("job-") or not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path)
            marker = path / "owner"
            try:
                if marker.is_symlink() or marker.stat().st_size > 128:
                    continue
                pid_value, identity = marker.read_text().split(":")
                pid = int(pid_value)
            except (OSError, ValueError):
                continue
            if path.stat().st_uid == os.getuid() and _process_identity(pid) != identity:
                shutil.rmtree(path)
    workspace = tempfile.TemporaryDirectory(prefix="job-", dir=root)
    current_identity = _process_identity(os.getpid())
    if current_identity is None:
        workspace.cleanup()
        raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED)
    (Path(workspace.name) / "owner").write_text(f"{os.getpid()}:{current_identity}")
    return workspace


def render_private_artifact(
    document: app.ReportDocumentReader, format: ReportFormat, *, cancelled: threading.Event
) -> app.RenderedArtifact:
    """One subprocess works with both standalone and Celery prefork workers."""
    manifest = document.manifest
    versions = {"report_sections_v1": "1", "report_sections_v2": "2", "report_sections_v3": "3"}
    profile = versions.get(report_profile_version(manifest.document.selection))
    if profile is None or manifest.document.document_schema_version != f"{profile}.0.0":
        raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
    parent, child = multiprocessing.Pipe(duplex=True)
    workspace = _workspace()
    process: subprocess.Popen[bytes] | None = None
    streams: dict[ReportTableKey, Iterator[ReportChunk]] = {}
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed module, typed enum, private descriptors
            [
                sys.executable,
                "-m",
                __name__,
                str(child.fileno()),
                format.value,
                workspace.name,
                str(os.getpid()),
                profile,
            ],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        )
        child.close()
        parent.send_bytes(encode_report_manifest(manifest))
        while True:
            if cancelled.is_set():
                raise app.ReportRenderError(ReportFailureCode.LEASE_EXPIRED)
            if not parent.poll(0.2):
                if process.poll() is not None:
                    raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED)
                continue
            message = parent.recv()
            if type(message) is not tuple or not message:
                raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED)
            if message == ("check",):
                parent.send(True)
            elif message[0] == "start" and len(message) == 2:
                table = ReportTableKey(message[1])
                previous = streams.get(table)
                close = getattr(previous, "close", None)
                if close is not None:
                    close()
                streams[table] = iter(document.iter_chunks(table))
            elif message[0] == "next" and len(message) == 3:
                table = ReportTableKey(message[1])
                if table not in streams or type(message[2]) is not int:
                    raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
                chunk = next(streams[table], None)
                if chunk is not None and chunk.ordinal != message[2]:
                    raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
                parent.send(chunk.canonical_bytes if chunk is not None else None)
            elif (
                message[0] == "done"
                and len(message) == 2
                and isinstance(message[1], app.RenderedArtifact)
            ):
                artifact = message[1]
                if artifact.format is not format or artifact.byte_length > 10 * 1024 * 1024:
                    raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
                if document.manifest != manifest:
                    raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
                return artifact
            elif message[0] == "failed" and len(message) == 2:
                raise app.ReportRenderError(ReportFailureCode(message[1]))
            else:
                raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED)
    except (EOFError, OSError):
        raise app.ReportRenderError(ReportFailureCode.RENDER_FAILED) from None
    finally:
        parent.close()
        child.close()
        for stream in streams.values():
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        if process is not None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        workspace.cleanup()


def _main() -> None:
    import ctypes

    if len(sys.argv) != 6:
        raise SystemExit(2)
    descriptor, format_value, scratch, parent_pid, profile = sys.argv[1:]
    if profile not in {"1", "2", "3"}:
        raise SystemExit(2)
    # Linux closes the entire renderer immediately if its owning worker dies.
    # Check the parent again after installing the signal to close the start race.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != int(parent_pid):
        raise SystemExit(2)
    connection = Connection(int(descriptor))
    payload = connection.recv_bytes(maxlength=2 * 1024 * 1024)
    _child(connection, payload, format_value, scratch, profile)


if __name__ == "__main__":
    _main()
