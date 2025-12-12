# Parallel Extraction & Scoring Implementation Plan

## Implementation Strategy with Backward Compatibility

### 1. Backward Compatibility Approach

#### Unified Flags Approach (Recommended)
```python
# Extend existing --parallel and --max-concurrent flags
# to control ALL parallel stages (candidates, extraction, scoring)

# Existing behavior preserved:
python post_generator.py --enable-synthesis  # Sequential processing (default)

# New parallel behavior:
python post_generator.py --parallel --max-concurrent 8 --enable-synthesis
# - Candidates: 8 concurrent
# - Extraction: 8 concurrent
# - Scoring: 8 concurrent

# All stages use the same concurrency setting for simplicity
```

**Recommendation**: Use unified flags for simplicity and user experience.

### 2. Function Signature Preservation

#### Current Functions (Must Remain Compatible)
```python
def extract_all_article_cards(candidates: List[ArticleCandidate], verbose: bool = False) -> List[ArticleCard]:
    """Existing signature - add parallel parameter internally"""

def score_all_cards_with_voting(cards: List[ArticleCard], criteria: Dict[str, Dict[str, Any]], votes: int = 3, verbose: bool = False) -> List[ArticleScore]:
    """Existing signature - add parallel parameter internally"""
```

#### New Wrapper Functions
```python
def extract_all_article_cards_parallel(candidates: List[ArticleCandidate], max_concurrent: int = 5, verbose: bool = False) -> List[ArticleCard]:
    """New parallel extraction function"""

def score_all_cards_with_voting_parallel(cards: List[ArticleCard], max_concurrent: int = 5, votes: int = 3, verbose: bool = False) -> List[ArticleScore]:
    """New parallel scoring function"""
```

### 3. Default Behavior Preservation

- **Default**: Sequential processing (current behavior)
- **Opt-in**: Parallel processing only when `--parallel` flag is used
- **Graceful Degradation**: If parallel fails, fall back to sequential

## Thread-Safety and Metrics Tracking Requirements

### 1. Global Metrics Thread-Safety

#### Current Implementation
```python
# Global metrics object (already thread-safe)
pipeline_metrics = PipelineMetrics()
_metrics_lock = threading.Lock()

def track_llm_call(stage_name: str, input_text: str, output_text: str, execution_time: float):
    """Thread-safe metrics tracking (already implemented)"""
    with _metrics_lock:
        # Update appropriate stage metrics
```

#### Parallel Extension Requirements
```python
class ThreadSafeParallelMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._extraction_metrics = StageMetrics("EXTRACT")
        self._scoring_metrics = StageMetrics("SCORE")
        
    def track_parallel_extraction(self, input_text: str, output_text: str, execution_time: float):
        """Thread-safe parallel extraction metrics"""
        with self._lock:
            self._extraction_metrics.add_input(input_text)
            self._extraction_metrics.add_output(output_text)
            self._extraction_metrics.add_execution_time(execution_time)
            self._extraction_metrics.llm_calls += 1
            
    def track_parallel_scoring(self, input_text: str, output_text: str, execution_time: float):
        """Thread-safe parallel scoring metrics"""
        with self._lock:
            self._scoring_metrics.add_input(input_text)
            self._scoring_metrics.add_output(output_text)
            self._scoring_metrics.add_execution_time(execution_time)
            self._scoring_metrics.llm_calls += 1
```

### 2. Progress Tracking Thread-Safety

```python
class ThreadSafeProgressTracker:
    def __init__(self, total_items: int, stage_name: str, verbose: bool = False):
        self.total = total_items
        self.completed = 0
        self.stage_name = stage_name
        self.verbose = verbose
        self.lock = threading.Lock()
        
    def update_progress(self, item_id: int, status: str = "completed"):
        """Thread-safe progress updates"""
        with self.lock:
            self.completed += 1
            if self.verbose and self.completed % max(1, self.total // 10) == 0:
                percentage = (self.completed / self.total) * 100
                print(f"[{self.stage_name}] Progress: {self.completed}/{self.total} ({percentage:.1f}%) - {status}")
```

### 3. Error Handling Thread-Safety

```python
class ThreadSafeErrorCollector:
    def __init__(self):
        self.errors = []
        self.lock = threading.Lock()
        
    def add_error(self, item_id: int, error: Exception):
        """Thread-safe error collection"""
        with self.lock:
            self.errors.append({
                'item_id': item_id,
                'error': str(error),
                'timestamp': time.time()
            })
            
    def get_errors(self) -> List[Dict]:
        """Get all collected errors"""
        with self.lock:
            return self.errors.copy()
```

## Progress Tracking and Error Handling Design

### 1. Extraction Stage Progress Tracking

```python
def extract_all_article_cards_parallel(
    candidates: List[ArticleCandidate],
    max_concurrent: int = 5,
    verbose: bool = False,
    retry_count: int = 3
) -> List[ArticleCard]:
    """Parallel extraction with comprehensive progress tracking"""
    
    if verbose:
        print(f"\n{'='*80}")
        print("PARALLEL EXTRACTION STAGE")
        print(f"{'='*80}")
        print(f"Extracting {len(candidates)} cards with max {max_concurrent} concurrent requests...")
    
    progress_tracker = ThreadSafeProgressTracker(len(candidates), "EXTRACT", verbose)
    error_collector = ThreadSafeErrorCollector()
    
    def worker_extract_card(candidate: ArticleCandidate) -> ArticleCard:
        """Worker function for parallel extraction"""
        try:
            card = extract_article_card(
                article_content=candidate.content,
                article_id=candidate.article_id,
                verbose=False,  # Reduce verbosity in workers
                retry_count=retry_count
            )
            progress_tracker.update_progress(candidate.article_id, "extracted")
            return card
        except Exception as e:
            error_collector.add_error(candidate.article_id, e)
            progress_tracker.update_progress(candidate.article_id, f"failed: {e}")
            raise  # Re-raise to be handled by ThreadPoolExecutor
    
    # Execute parallel extraction
    cards = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_candidate = {
            executor.submit(worker_extract_card, candidate): candidate.article_id
            for candidate in candidates
        }
        
        for future in as_completed(future_to_candidate):
            candidate_id = future_to_candidate[future]
            try:
                card = future.result()
                cards.append(card)
            except Exception as e:
                if verbose:
                    print(f"  ✗ Failed to extract Article #{candidate_id}: {e}")
                # Continue with other cards
    
    # Report final statistics
    if verbose:
        successful = len(cards)
        failed = len(error_collector.get_errors())
        print(f"✓ Parallel extraction complete: {successful}/{len(candidates)} cards extracted")
        if failed > 0:
            print(f"  Failed extractions: {failed}")
            for error in error_collector.get_errors()[:3]:  # Show first 3
                print(f"    - Article #{error['item_id']}: {error['error']}")
        print()
    
    return cards
```

### 2. Scoring Stage Progress Tracking

```python
def score_all_cards_with_voting_parallel(
    cards: List[ArticleCard],
    max_concurrent: int = 5,
    votes: int = 3,
    criteria: Dict[str, Dict[str, Any]] = SCORING_CRITERIA,
    verbose: bool = False
) -> List[ArticleScore]:
    """Parallel scoring with comprehensive progress tracking"""
    
    if verbose:
        print(f"\n{'='*80}")
        print("PARALLEL SCORING STAGE")
        print(f"{'='*80}")
        print(f"Scoring {len(cards)} cards with {votes} votes each, max {max_concurrent} concurrent...")
    
    total_scoring_operations = len(cards) * votes
    progress_tracker = ThreadSafeProgressTracker(total_scoring_operations, "SCORE", verbose)
    error_collector = ThreadSafeErrorCollector()
    
    def worker_score_single_vote(card: ArticleCard, vote_number: int) -> ArticleScore:
        """Worker function for single vote scoring"""
        try:
            score = score_article_card(card, criteria, verbose=False)
            progress_tracker.update_progress(f"{card.article_id}-{vote_number}", f"vote{vote_number}_completed")
            return score
        except Exception as e:
            error_collector.add_error(f"{card.article_id}-{vote_number}", e)
            progress_tracker.update_progress(f"{card.article_id}-{vote_number}", f"vote{vote_number}_failed: {e}")
            raise
    
    def worker_score_all_votes_for_card(card: ArticleCard) -> ArticleScore:
        """Worker function to score one card with all votes"""
        card_votes = []
        for vote_num in range(votes):
            try:
                vote_score = worker_score_single_vote(card, vote_num + 1)
                card_votes.append(vote_score)
            except Exception as e:
                if verbose:
                    print(f"    ⚠ Vote {vote_num + 1} failed for card {card.article_id}: {e}")
        
        if card_votes:
            return average_score_votes(card_votes)
        else:
            raise RuntimeError(f"All votes failed for card {card.article_id}")
    
    # Execute parallel scoring
    all_scores = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_card = {
            executor.submit(worker_score_all_votes_for_card, card): card.article_id
            for card in cards
        }
        
        for future in as_completed(future_to_card):
            card_id = future_to_card[future]
            try:
                score = future.result()
                all_scores.append(score)
                if verbose:
                    print(f"  ✓ Card #{card_id} scored: {score.overall_score}")
            except Exception as e:
                if verbose:
                    print(f"  ✗ Failed to score Card #{card_id}: {e}")
    
    # Report final statistics
    if verbose:
        scores_list = [s.overall_score for s in all_scores]
        print(f"✓ Parallel scoring complete: {len(all_scores)}/{len(cards)} cards scored")
        if scores_list:
            print(f"  Score range: {min(scores_list):.1f} - {max(scores_list):.1f}")
        failed = len(error_collector.get_errors())
        if failed > 0:
            print(f"  Failed scoring operations: {failed}")
        print()
    
    return all_scores
```

## Command-Line Interface Changes

### 1. Extended Argument Parser

```python
def setup_argument_parser():
    parser = argparse.ArgumentParser(
        description="Generate marketing blog posts with optional synthesis pipeline. Supports parallel processing."
    )
    
    # ... existing arguments ...
    
    # Parallel processing flags
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable parallel processing for candidates, extraction, and scoring stages"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent LLM requests for parallel stages (default: 5)"
    )
    parser.add_argument(
        "--extract-concurrent",
        type=int,
        default=None,
        help="Maximum concurrent requests for extraction stage (overrides --max-concurrent)"
    )
    parser.add_argument(
        "--score-concurrent", 
        type=int,
        default=None,
        help="Maximum concurrent requests for scoring stage (overrides --max-concurrent)"
    )
    
    return parser
```

### 2. Usage Pattern Documentation

#### Basic Parallel Usage
```bash
# Parallel processing with unified concurrency control
python post_generator.py --topic-file my_topic.txt --iterations 15 --enable-synthesis --parallel --max-concurrent 8

# Equivalent to:
# - Candidates: 8 concurrent
# - Extraction: 8 concurrent
# - Scoring: 8 concurrent
```

#### Advanced Parallel Usage
```bash
# Stage-specific concurrency control
python post_generator.py --topic-file my_topic.txt --iterations 20 --enable-synthesis --parallel --extract-concurrent 6 --score-concurrent 10

# Fine-grained control:
# - Candidates: default max_concurrent (5)
# - Extraction: 6 concurrent
# - Scoring: 10 concurrent
```

#### Legacy Sequential Usage (Preserved)
```bash
# Sequential processing (default behavior)
python post_generator.py --topic-file my_topic.txt --iterations 15 --enable-synthesis

# Explicit sequential
python post_generator.py --topic-file my_topic.txt --iterations 15 --enable-synthesis --max-concurrent 1
```

### 3. Help Text Enhancement

```python
# Enhanced help for parallel options
"""
Parallel Processing Options:
  --parallel              Enable parallel processing for all stages
  --max-concurrent N      Concurrent requests for all parallel stages (default: 5)

Performance Notes:
  - Parallel processing requires --iterations >= 5 for meaningful speedup
  - Extraction stage: ~3-5x speedup with parallel processing
  - Scoring stage: ~2-4x speedup depending on vote count
  - Overall pipeline: 2-6x speedup potential
  - Higher concurrency may hit API rate limits
"""
```

## Implementation Roadmap

### Phase 1: Core Infrastructure (Week 1)
1. Create thread-safe metrics tracking classes
2. Implement worker functions for extraction and scoring
3. Add progress tracking infrastructure
4. Create basic parallel wrapper functions

### Phase 2: Integration (Week 2)
1. Integrate parallel functions with existing pipeline
2. Add command-line argument parsing
3. Implement backward compatibility layer
4. Add comprehensive error handling

### Phase 3: Testing & Validation (Week 3)
1. Unit tests for individual components
2. Integration tests with various data sizes
3. Performance benchmarking across concurrency levels
4. Backward compatibility verification

### Phase 4: Optimization & Documentation (Week 4)
1. Performance tuning and memory optimization
2. Advanced error recovery mechanisms
3. Comprehensive documentation and examples
4. Final testing and release preparation

## Risk Mitigation Strategies

### 1. API Rate Limiting
- Implement exponential backoff in worker functions
- Add adaptive concurrency based on response times
- Monitor and adjust concurrency dynamically

### 2. Memory Usage
- Limit concurrent operations based on available memory
- Implement streaming for large text processing
- Add memory usage monitoring and alerts

### 3. Error Recovery
- Graceful degradation from parallel to sequential
- Comprehensive error logging and reporting
- Retry mechanisms with exponential backoff

### 4. Data Integrity
- Thread-safe metrics collection
- Consistent vote averaging in parallel scoring
- Proper synchronization of shared resources

This implementation plan provides a comprehensive roadmap for adding parallel processing to the extraction and scoring stages while maintaining full backward compatibility and robust error handling.