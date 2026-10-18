"""Locked recovery journal for wrapped commands (no D-Bus at import)."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


def state_directory():
    override = os.environ.get('AUTOHDR_STATE_DIR')
    if override:
        return Path(override)
    # Keep the journal location across the package rename so interrupted HDR
    # sessions from older builds remain recoverable.
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'steam-auto-hdr'


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'start': fields[19]}
    except (OSError, IndexError):
        return None


def is_alive(identity):
    return process_identity(identity['pid']) == identity


def atomic_json(path, value):
    """Commit recovery data before touching the display, including directory fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Sessions:
    def __init__(self, directory=None, backend=None, alive=is_alive):
        self.directory = Path(directory) if directory is not None else state_directory()
        self.path = self.directory / 'sessions.json'
        self.backend = backend
        self.alive = alive

    def display(self):
        if self.backend is None:
            import mutter
            self.backend = mutter
        return self.backend

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / 'sessions.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                journal = json.loads(self.path.read_text())
                if journal.get('version') != 1 or not isinstance(journal.get('monitors'), dict):
                    raise RuntimeError(f'Unsupported recovery journal: {self.path}')
            else:
                journal = {'version': 1, 'monitors': {}}
            yield journal

    def save(self, journal):
        atomic_json(self.path, journal)

    def recover_locked(self, journal):
        errors = []
        for connector, entry in list(journal['monitors'].items()):
            entry['sessions'] = [session for session in entry['sessions'] if self.alive(session)]
            self.save(journal)
            if not entry['sessions']:
                try:
                    self.display().restore(entry['snapshot'])
                except Exception as exc:
                    errors.append(f'{connector}: {exc}')
                else:
                    del journal['monitors'][connector]
                    self.save(journal)
        return errors

    def recover(self):
        with self.locked() as journal:
            errors = self.recover_locked(journal)
        if errors:
            raise RuntimeError('; '.join(errors))

    def acquire(self, connector=None):
        identity = process_identity()
        if identity is None:
            raise RuntimeError('Cannot identify supervisor process via /proc')
        with self.locked() as journal:
            errors = self.recover_locked(journal)
            if errors:
                raise RuntimeError('Pending recovery failed: ' + '; '.join(errors))
            snapshot = self.display().snapshot(connector)
            connector = snapshot['connector']
            entry = journal['monitors'].setdefault(connector, {'snapshot': snapshot, 'sessions': []})
            entry['sessions'].append(identity)
            # The first session's snapshot survives overlapping sessions and crashes.
            self.save(journal)
            try:
                self.display().enable(snapshot)
            except Exception:
                entry['sessions'].remove(identity)
                self.save(journal)
                # Keep the original journal if rollback fails or the D-Bus reply was lost.
                self.recover_locked(journal)
                raise
        return connector, identity

    def release(self, lease):
        connector, identity = lease
        with self.locked() as journal:
            entry = journal['monitors'].get(connector)
            if entry is not None:
                entry['sessions'] = [session for session in entry['sessions'] if session != identity]
                self.save(journal)
            errors = self.recover_locked(journal)
        if errors:
            raise RuntimeError('; '.join(errors))
