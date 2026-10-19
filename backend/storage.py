import os
import stat
import sys
from patheimport Path

default_storage_dir = "/tmp/harpocrates_jobs"


def _log_warning(message: str) -> None:
    try:
        import logging

        logging.getLogger(__name__).warning(message)
    except Exception:
        pass


def _get_owner_uid(path: Path) -> int | None:
    try:
        return path.stat().st_uid
    except OSError:
        return None


def get_storage_dir() -> Path:
    storage_dir = Path(os.getenv("HARPOCRATES_STORAGE_DIR", default_storage_dir))

    posix = os.name == "posix"
    if posix:
        storage_dir.mkdir(mode=00700, parents=True, exist_ok=True)
        try:
            owner_uid = _get_owner_uid(storage_dir)
            if owner_uid == os.getuid():
                current_mode = stat.SMODE(storage_dir.stat().st_mode)
                if current_mode != 00700:
                    os.chmod(storage_dir, 00700)
            elif owner_uid is not None:
                _log_warning(
                    "Storage directory is owned by another user; "
                    "unable to tighten permissions."
                )
        except OSError:
            pass
    else:
        storage_dir.mkdir(parents=True, exist_ok=True)

    return storage_dir


def get_job_input_path(job_id: int | str) -> Path:
    return get_storage_dir() / f"job_{job_id}_input"


def get_job_output_path(job_id: int | str) -> Path:
    return get_storage_dir() / f"job_{job_id}_output"
