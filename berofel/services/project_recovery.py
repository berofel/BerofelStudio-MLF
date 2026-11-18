"""Safe discovery and loading of project autosaves."""
from pathlib import Path
from contextlib import nullcontext

from berofel.core.project import Project


def autosave_path(project_path: str | Path) -> Path:
    path = Path(project_path)
    return path.with_name(path.name + '.autosave')


def newer_autosave_project(project_path: str | Path) -> tuple[Path | None, Project | None]:
    """Validate and load a recovery point once for the open-project flow."""
    original = Path(project_path)
    backup = autosave_path(original)
    try:
        if not original.is_file() or not backup.is_file():
            return None,None
        if backup.stat().st_mtime_ns <= original.stat().st_mtime_ns:
            return None,None
        if original.read_bytes() == backup.read_bytes():
            return None,None
        # Only offer a recovery point that the current project loader can
        # actually reopen. A truncated/newer autosave must not block the
        # user's valid canonical project from opening.
        project=Project.load(str(backup))
        project.path=str(original.resolve())
    except Exception:
        return None,None
    return backup,project


def newer_autosave(project_path: str | Path) -> Path | None:
    """Return a useful autosave only when it is newer and differs from disk."""
    return newer_autosave_project(project_path)[0]


def load_project(project_path: str | Path, recover: bool = False) -> Project:
    """Load the selected snapshot while keeping Save pointed at the source."""
    original = Path(project_path).resolve()
    project=(newer_autosave_project(original)[1] if recover else None)
    if project is None:
        project=Project.load(str(original))
    project.path = str(original)
    return project


def write_autosave_snapshot(project_snapshot: Project, project_path: str | Path,
                            expected_mtime_ns: int | None = None,
                            io_lock=None) -> Path | None:
    """Atomically save a detached snapshot next to the canonical project."""
    original = Path(project_path).resolve()
    destination = autosave_path(original)
    with io_lock if io_lock is not None else nullcontext():
        if expected_mtime_ns is not None:
            try:
                if original.stat().st_mtime_ns != expected_mtime_ns:
                    return None
            except OSError:
                return None
        snapshot_path = project_snapshot.path
        try:
            project_snapshot.save(str(destination))
        finally:
            project_snapshot.path = snapshot_path
        return destination
