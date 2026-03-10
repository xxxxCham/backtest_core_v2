"""
Module-ID: performance.__init__

Purpose: Package performance - exports profiler, parallel, monitor, GPU, benchmarks.

Role in pipeline: performance optimization & observability

Key components: Re-exports ParallelRunner, Profiler, PerformanceMonitor, GPUIndicatorCalculator

Inputs: None (module imports only)

Outputs: Public API via __all__

Dependencies: .profiler, .parallel, .monitor, .memory, .gpu, .device_backend, .benchmark

Conventions: __all__ définit API publique; imports conditionnels pour optional deps.

Read-if: Modification exports ou module structure.

Skip-if: Vous importez directement depuis performance.profiler.
"""

from performance.memory import (
    ChunkedProcessor,
    DataFrameCache,
    MemoryManager,
    MemoryStats,
    estimate_memory_needed,
    get_available_ram_gb,
    get_memory_info,
    memory_efficient_mode,
    optimize_dataframe,
)
from performance.monitor import (
    PerformanceMonitor,
    ProgressBar,
    ResourceStats,
    ResourceTracker,
    get_system_resources,
    print_system_info,
)
from performance.parallel import (
    ParallelConfig,
    ParallelRunner,
    SweepResult,
    benchmark_parallel_configs,
    generate_param_grid,
    get_recommended_chunk_size,
    get_recommended_joblib_batch_size,
    get_recommended_max_in_flight,
    get_recommended_worker_count,
    parallel_sweep,
)
from performance.profiler import (
    Profiler,
    ProfileResult,
    TimingContext,
    benchmark_function,
    profile_function,
    profile_memory,
    run_with_profiling,
)

__all__ = [
    # Parallel
    "ParallelRunner",
    "ParallelConfig",
    "SweepResult",
    "parallel_sweep",
    "generate_param_grid",
    "benchmark_parallel_configs",
    "get_recommended_worker_count",
    "get_recommended_chunk_size",
    "get_recommended_max_in_flight",
    "get_recommended_joblib_batch_size",
    # Monitor
    "PerformanceMonitor",
    "ResourceTracker",
    "ResourceStats",
    "ProgressBar",
    "print_system_info",
    "get_system_resources",
    # Profiler
    "Profiler",
    "ProfileResult",
    "profile_function",
    "profile_memory",
    "TimingContext",
    "run_with_profiling",
    "benchmark_function",
    # Memory
    "ChunkedProcessor",
    "MemoryManager",
    "DataFrameCache",
    "MemoryStats",
    "get_memory_info",
    "get_available_ram_gb",
    "optimize_dataframe",
    "estimate_memory_needed",
    "memory_efficient_mode",
]
