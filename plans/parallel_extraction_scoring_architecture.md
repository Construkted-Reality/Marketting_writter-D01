# Parallel Extraction & Scoring Architecture

## Overview
Extend the parallelization strategy from candidate generation to the EXTRACT and SCORE stages of the article synthesis pipeline. Transform sequential processing into concurrent execution using Python's ThreadPoolExecutor while maintaining thread-safety and backward compatibility.

## Current Sequential Implementation Analysis

### Extraction Stage (lines 519-530)
- **Function**: `extract_all_article_cards()`
- **Pattern**: Sequential for loop processing candidates one by one
- **LLM Calls**: 1 per candidate article
- **Error Handling**: Individual failures caught, process continues
- **Progress Tracking**: Verbose output with completion status

### Scoring Stage (lines 677-698)  
- **Function**: `score_all_cards_with_voting()`
- **Pattern**: Nested loops - cards sequentially, votes sequentially per card
- **LLM Calls**: votes × cards (default 3 votes per card)
- **Error Handling**: Individual vote failures caught, averaging continues
- **Progress Tracking**: Verbose output with per-vote and per-card status

## Architecture Components

### 1. Parallel Extraction Classes

```python
class ParallelArticleExtractor:
    def __init__(self, max_concurrent_requests: int = 5, verbose: bool = False):
        self.max_concurrent = max_concurrent_requests
        self.verbose = verbose
        self.errors = []
        self.progress_lock = threading.Lock()
        
    def extract_cards_parallel(
        self, 
        candidates: List[ArticleCandidate],
        retry_count: int = 3,
        **llm_kwargs
    ) -> List[ArticleCard]:
        """Main method to extract cards in parallel"""
        pass

class ThreadSafeExtractionMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._extraction_stage = StageMetrics("EXTRACT")
        
    def track_extraction_call_safe(self, input_text: str, 
                                  output_text: str, execution_time: float):
        """Thread-safe version of extraction metrics tracking"""
        with self._lock:
            # Call existing track_llm_call with "EXTRACT" stage
```

### 2. Parallel Scoring Classes

```python
class ParallelCardScorer:
    def __init__(self, max_concurrent_requests: int = 5, verbose: bool = False):
        self.max_concurrent = max_concurrent_requests
        self.verbose = verbose
        self.errors = []
        self.progress_lock = threading.Lock()
        
    def score_cards_parallel(
        self, 
        cards: List[ArticleCard],
        criteria: Dict[str, Dict[str, Any]],
        votes: int = 3,
        **llm_kwargs
    ) -> List[ArticleScore]:
        """Main method to score cards in parallel with voting"""
        pass

class ThreadSafeScoringMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._scoring_stage = StageMetrics("SCORE")
        
    def track_scoring_call_safe(self, input_text: str, 
                               output_text: str, execution_time: float):
        """Thread-safe version of scoring metrics tracking"""
        with self._lock:
            # Call existing track_llm_call with "SCORE" stage
```

### 3. Worker Functions for ThreadPoolExecutor

```python
def extract_single_card_worker(
    candidate: ArticleCandidate,
    retry_count: int,
    verbose: bool
) -> ArticleCard:
    """Worker function for parallel card extraction"""
    pass

def score_single_vote_worker(
    card: ArticleCard,
    criteria: Dict[str, Dict[str, Any]],
    vote_number: int,
    verbose: bool
) -> ArticleScore:
    """Worker function for parallel card scoring"""
    pass
```

### 4. Progress Tracking System

```python
class ParallelProgressTracker:
    def __init__(self, total_items: int, stage_name: str, verbose: bool = False):
        self.total = total_items
        self.completed = 0
        self.stage_name = stage_name
        self.verbose = verbose
        self.start_time = time.time()
        
    def update_progress(self, item_id: int, status: str):
        """Update and display progress for parallel operations"""
        pass
```

## Implementation Strategy

### Phase 1: Core Parallel Extraction
1. Replace sequential loop in `extract_all_article_cards()` with ThreadPoolExecutor
2. Implement thread-safe extraction metrics tracking
3. Add configurable concurrency limits for extraction stage
4. Maintain existing error handling and retry mechanisms

### Phase 2: Core Parallel Scoring  
1. Replace nested sequential loops in `score_all_cards_with_voting()` with ThreadPoolExecutor
2. Implement parallel voting system with thread-safe metrics
3. Add configurable concurrency limits for scoring stage
4. Maintain existing vote averaging and error handling

### Phase 3: Enhanced Features
1. Unified progress tracking across both parallel stages
2. Advanced error handling with per-stage retry mechanisms
3. Resource usage monitoring and adaptive concurrency
4. Performance metrics collection for parallel operations

### Phase 4: Integration & Optimization
1. Integrate with existing command-line flags (`--parallel`, `--max-concurrent`)
2. Dynamic concurrency adjustment based on API response times
3. Memory usage optimization for large-scale parallel operations
4. Comprehensive testing and validation

## Key Benefits

1. **Performance**: 
   - Extraction stage: 3-5x speedup for large candidate counts
   - Scoring stage: 3x speedup for default 3-vote configuration
   - Combined pipeline: Potential 4-8x overall speedup

2. **Resource Utilization**: Better utilization of available system and API resources

3. **Scalability**: Configurable concurrency to match API limits and system capacity

4. **Reliability**: Graceful handling of individual extraction/score failures

5. **Monitoring**: Real-time progress tracking and performance metrics for both stages

## Risk Mitigation

1. **API Rate Limiting**: Implement exponential backoff and request queuing
2. **Memory Usage**: Limit concurrent operations and implement streaming where possible
3. **Error Propagation**: Ensure individual failures don't crash entire stage
4. **Metrics Accuracy**: Thread-safe metrics collection with proper synchronization
5. **Vote Consistency**: Maintain voting integrity in parallel scoring environment

## Backward Compatibility

- Maintain all existing function signatures and return types
- Preserve existing CLI argument structure and defaults
- Keep parallelization optional (default to sequential for safety)
- Maintain identical output file organization and naming
- Ensure existing error handling and retry mechanisms remain intact

## Command-Line Interface Extensions

```bash
# Enable parallel processing for all stages
python post_generator.py --parallel --max-concurrent 10 --enable-synthesis
# - Candidates: 10 concurrent
# - Extraction: 10 concurrent
# - Scoring: 10 concurrent

# Legacy behavior preserved
python post_generator.py --enable-synthesis  # Sequential processing (default)
```

## Performance Expectations

- **Extraction Stage**: 3-5x speedup for 10-50 candidates
- **Scoring Stage**: 2-4x speedup for 10-50 cards (depending on vote count)
- **Overall Pipeline**: 2-6x speedup for complete synthesis pipeline
- **Memory Usage**: Linear increase with concurrency level
- **API Load**: Proportional to concurrency setting

## Testing Strategy

1. **Unit Tests**: Individual worker functions and thread-safe components
2. **Integration Tests**: End-to-end pipeline with various concurrency settings
3. **Performance Tests**: Speedup measurements across different data sizes
4. **Reliability Tests**: Failure injection and recovery validation
5. **Compatibility Tests**: Backward compatibility verification with existing workflows