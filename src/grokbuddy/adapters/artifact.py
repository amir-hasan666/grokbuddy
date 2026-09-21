import hashlib
import os
from pathlib import Path
import re
import tempfile

from grokbuddy.domain.model import HubError


class FileArtifactStore:
    def __init__(self, root, max_bytes=50 * 1024 * 1024):
        original = Path(root).absolute()
        for item in (original, *original.parents):
            if item.is_symlink() or item.is_junction():
                raise HubError('Artifact root must not traverse a link')
        original.mkdir(parents=True, exist_ok=True)
        self.root = original.resolve()
        self.max_bytes = max_bytes

    def _path(self, pointer):
        if not re.fullmatch(r'sha256/[0-9a-f]{2}/[0-9a-f]{64}', pointer):
            raise HubError('Invalid artifact pointer')
        parts = pointer.split('/')
        if parts[1] != parts[2][:2]:
            raise HubError('Invalid content address')
        path = self.root.joinpath(*parts)
        for item in (self.root, path.parent.parent, path.parent, path):
            if item.is_symlink() or item.is_junction():
                raise HubError('Artifact links are forbidden')
        if not path.resolve().is_relative_to(self.root):
            raise HubError('Artifact outside storage root')
        return path

    def put(self, content):
        if not isinstance(content, bytes) or len(content) > self.max_bytes:
            raise HubError('Invalid artifact bytes or size')
        sha = hashlib.sha256(content).hexdigest()
        pointer = f'sha256/{sha[:2]}/{sha}'
        path = self._path(pointer)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.read(pointer, sha, len(content))
            return pointer, sha
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.staging-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._path(pointer)
            # Atomic content-address publication; same-hash concurrent writers have identical bytes.
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return pointer, sha

    def read(self, pointer, expected_hash, size):
        path = self._path(pointer)
        if not isinstance(size, int) or not 0 <= size <= self.max_bytes:
            raise HubError('Invalid artifact size')
        try:
            with path.open('rb') as stream:
                content = stream.read(self.max_bytes + 1)
        except OSError as exc:
            raise HubError('Artifact unavailable') from exc
        if len(content) != size or hashlib.sha256(content).hexdigest() != expected_hash:
            raise HubError('Artifact integrity failure')
        return content
