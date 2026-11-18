"""Hardware-aware defaults for CPU-bound preview and local AI work."""
from __future__ import annotations

from dataclasses import dataclass
import os

try:
    import psutil
except ImportError:  # psutil is optional for source-only deployments
    psutil = None


@dataclass(frozen=True)
class PerformanceProfile:
    level: str
    logical_cpus: int
    total_memory_mb: int
    available_memory_mb: int
    preview_threads: int
    ai_threads: int
    export_threads: int


def profile_for_resources(logical_cpus: int, total_memory_bytes: int,
                          available_memory_bytes: int) -> PerformanceProfile:
    """Choose conservative defaults while leaving headroom for the editor."""
    cpus = max(1, int(logical_cpus or 1))
    total_mb = max(0, int(total_memory_bytes) // (1024 * 1024))
    available_mb = max(0, int(available_memory_bytes) // (1024 * 1024))

    if cpus <= 2 or total_mb < 8192 or available_mb < 1536:
        level = 'economia'
        preview_threads = 1
        ai_threads = max(1, min(2, cpus - 1))
        export_threads = max(1, min(2, cpus - 1))
    elif cpus >= 12 and total_mb >= 16384 and available_mb >= 6144:
        level = 'desempenho'
        preview_threads = min(4, max(3, cpus // 6))
        ai_threads = min(8, max(4, cpus - 2))
        export_threads = min(16, max(8, cpus - 2))
    else:
        level = 'equilibrado'
        preview_threads = 2 if cpus >= 6 else 1
        ai_threads = min(4, max(2, cpus - 1))
        export_threads = min(6, max(2, cpus - 2))

    return PerformanceProfile(level, cpus, total_mb, available_mb,
                              preview_threads, ai_threads, export_threads)


def current_profile() -> PerformanceProfile:
    cpus = os.cpu_count() or 1
    if psutil is not None:
        try:
            memory = psutil.virtual_memory()
            return profile_for_resources(cpus, memory.total, memory.available)
        except (OSError, RuntimeError):
            pass
    # Unknown memory: avoid assuming a large workstation and preserve UI headroom.
    return profile_for_resources(cpus, 0, 0)


def qwen_limits(profile: PerformanceProfile | None = None) -> tuple[int, int]:
    """Return context tokens and prompt characters matched to currently free RAM."""
    profile = profile or current_profile()
    available = profile.available_memory_mb
    if available < 1024:
        context_size = 2048
    elif profile.level == 'economia' or available < 4096:
        context_size = 4096
    elif profile.level == 'desempenho' and available >= 12288:
        context_size = 16384
    else:
        context_size = 8192
    # Keep JSON framing and Portuguese word lengths inside the selected context.
    prompt_max_chars = context_size * 2
    return context_size, prompt_max_chars


def qwen_threads(profile: PerformanceProfile | None = None) -> int:
    """Use more cores for local Qwen only when RAM and CPU leave UI headroom."""
    profile=profile or current_profile()
    if (profile.logical_cpus>=12 and profile.total_memory_mb>=15_360 and
            profile.available_memory_mb>=6_144):
        if profile.logical_cpus>=16:
            # An 800-word local run was ~4% faster at 12 vs 8 threads on the
            # reference 16-logical-CPU machine; reserve four cores for UI/audio.
            return min(12,max(profile.ai_threads,(profile.logical_cpus*3)//4))
        return min(8,max(profile.ai_threads,profile.logical_cpus//2))
    return profile.ai_threads
