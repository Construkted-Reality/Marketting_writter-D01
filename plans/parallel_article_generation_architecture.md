# Parallel Article Generation Architecture

## Overview
Transform the sequential CANDIDATES stage (lines 1434-1491 in post_generator.py) into a concurrent system that generates multiple articles simultaneously using Python's ThreadPoolExecutor.

## Architecture Components

### 1. ParallelCandidateGenerator Class
```python
class ParallelCandidateGenerator:
    def __init__(self, max_concurrent_requests: int = 5, verbose: bool = False):
        self.max_concurrent = max_concurrent_requests
        self.verbose = verbose
        self.results = []
        self.errors = []
        self.progress_lock = threading.Lock()
        
    def generate_candidates_parallel(
        self, 
        iterations: int, 
        generation_system_prompt: str, 
        generation_user_prompt: str,
        output_base: str,
        **llm_kwargs
    ) -> List[ArticleCandidate]:
        """Main method to generate candidates in parallel"""
        pass
```

### 2. Thread-Safe Metrics Tracking
```python
class ThreadSafeMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._candidates_stage = StageMetrics("CANDIDATES")
        
    def track_llm_call_safe(self, stage_name: str, input_text: str, 
                          output_text: str, execution_time: float):
        """Thread-safe version of track_llm_call"""
        with self._lock:
            # Call existing track_llm_call logic
```

### 3. Concurrent File Operations
```python
class ConcurrentFileWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self._file_locks = {}
        
    def write_candidate_safely(self, iteration: int, content: str, 
                             word_count: int, output_base: str):
        """Thread-safe candidate file writing"""
        pass
```

### 4. Progress Tracking System
```python
class ProgressTracker:
    def __init__(self, total: int, verbose: bool = False):
        self.total = total
        self.completed = 0
        self.verbose = verbose
        self.start_time = time.time()
        
    def update_progress(self, iteration: int, status: str):
        """Update and display progress"""
        pass
```

## Implementation Strategy

### Phase 1: Core Parallel Generation
1. Replace sequential for loop (lines 1434-1491) with ThreadPoolExecutor
2. Implement thread-safe metrics tracking
3. Add configurable concurrency limits
4. Maintain existing file organization structure

### Phase 2: Enhanced Features
1. Progress tracking and real-time updates
2. Advanced error handling and retry mechanisms
3. Resource usage monitoring
4. Adaptive concurrency based on API response times

### Phase 3: Optimization
1. Dynamic concurrency adjustment
2. Intelligent batching strategies
3. Memory usage optimization
4. Performance metrics collection

## Key Benefits

1. **Performance**: Potential 3-5x speedup for large iteration counts
2. **Resource Utilization**: Better utilization of available system resources
3. **Scalability**: Configurable concurrency to match API limits
4. **Reliability**: Graceful handling of individual request failures
5. **Monitoring**: Real-time progress tracking and performance metrics

## Risk Mitigation

1. **API Rate Limiting**: Implement exponential backoff and request queuing
2. **Memory Usage**: Limit concurrent requests and implement streaming where possible
3. **Error Propagation**: Ensure individual failures don't crash entire process
4. **File Conflicts**: Use thread-safe file operations with proper locking
5. **Metrics Accuracy**: Thread-safe metrics collection with proper synchronization

## Backward Compatibility

- Maintain all existing function signatures and return types
- Preserve existing CLI argument structure
- Keep optional parallelization (default to sequential for safety)
- Maintain identical output file organization and naming