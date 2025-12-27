# Implementation Plan: Candidates Only & Candidates Directory Modes

## Overview

This document details the implementation plan for adding two new modes to `post_generator.py`:

1. **`--candidates-only`** - Generate candidate articles only, skip synthesis pipeline
2. **`--candidates-dir`** - Load pre-generated candidates from a folder and run synthesis pipeline (EXTRACT → SCORE → SELECT → SYNTHESIZE → VALIDATE)

Additionally, the existing `--enable-synthesis` flag will be removed, with the default behavior being to run the full pipeline.

## Current Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Current Pipeline Architecture                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│   │ CANDIDATE │──▶│  EXTRACT  │──▶│   SCORE   │──▶│  SELECT   │    │
│   │   STAGE   │    │   STAGE   │    │   STAGE   │    │   STAGE   │    │
│   └──────────┘    └──────────┘    └──────────┘    └──────────┘    │
│                                                                     │
│                        ┌──────────┐    ┌──────────┐                 │
│                        │ SYNTHESIZE│──▶│ VALIDATE │                 │
│                        │   STAGE   │    │  STAGE   │                 │
│                        └──────────┘    └──────────┘                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## New Pipeline Modes Options

### Mode 1: `--candidates-only` (Generate Only)
```
┌──────────┐
│ CANDIDATE │──▶ [STOP - Skip remaining stages]
│   STAGE   │
└──────────┘
```

### Mode 2: `--candidates-dir` (Process Existing)
```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ LOAD FROM │──▶│  EXTRACT  │──▶│   SCORE   │──▶│  SELECT   │──▶│SYNTHESIZE│
│   DISK    │    │   STAGE   │    │   STAGE   │    │   STAGE   │    │  STAGE   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                    │
                        ┌───────────────────────────┘
                        │
                   ┌──────────┐
                   │ VALIDATE │
                   │  STAGE   │
                   └──────────┘
```

### Mode 3: Default (Full Pipeline)
```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ CANDIDATE │──▶│  EXTRACT  │──▶│   SCORE   │──▶│  SELECT   │──▶│SYNTHESIZE│
│   STAGE   │    │   STAGE   │    │   STAGE   │    │   STAGE   │    │  STAGE   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                    │
                        ┌───────────────────────────┘
                        │
                   ┌──────────┐
                   │ VALIDATE │
                   │  STAGE   │
                   └──────────┘
```

## Implementation Steps

### Step 1: Remove `--enable-synthesis` Flag

**File**: `post_generator.py`
**Lines**: 1867-1871 (argument definition), 2054-2083 (usage in main)

**Changes**:
1. Remove argument definition:
   ```python
   # REMOVE THIS:
   parser.add_argument(
       "--enable-synthesis",
       action="store_true",
       help="Enable 5-stage synthesis pipeline (requires --iterations >= 10)"
   )
   ```

2. Remove validation check:
   ```python
   # REMOVE THIS:
   if args.enable_synthesis and args.iteration < 10:
       print("Warning: Synthesis pipeline recommended with --iteration >= 10")
       print("Proceeding anyway...")
   ```

3. Remove synthesis pipeline execution block:
   ```python
   # REMOVE THIS:
   if args.enable_synthesis:
       pipeline = ArticleSynthesisPipeline(verbose=args.verbose)
       result = pipeline.run(...)
       # ... rest of synthesis logic
   ```

### Step 2: Add `--candidates-only` Flag

**Location**: After existing generation arguments (around line 1865)

**Code to Add**:
```python
parser.add_argument(
    "--candidates-only",
    action="store_true",
    help="Generate candidate articles only, skip synthesis pipeline"
)
```

### Step 3: Add `--candidates-dir` Flag

**Location**: After `--candidates-only` argument

**Code to Add**:
```python
parser.add_argument(
    "--candidates-dir",
    help="Path to folder containing candidate markdown files. Skips candidate generation and loads from files."
)
```

### Step 4: Add Function to Load Candidates Files

**New Function**: `load_candidates_files_from_folder()`

**Location**: Add near the candidate generation functions (around line 1711)

**Code to Add**:
```python
def load_candidate_files(
    candidates_dir: str,
    verbose: bool = False
) -> List[ArticleCandidate]:
    """
    Load pre-generated candidate articles from markdown files in a folder.
    
    Args:
        candidates_dir: Path to folder containing candidate markdown files
        verbose: Enable progress logging
        
    Returns:
        List of ArticleCandidate objects
    """
    if verbose:
        print(f"\n{'='*80}")
        print("LOADING CANDIDATES FROM DISK")
        print(f"{'='*80}")
        print(f"Loading candidates from: {candidates_dir}")
    
    candidates = []
    candidates_path = Path(candidates_dir)
    
    if not candidates_path.exists():
        raise FileNotFoundError(f"Candidates directory not found: {candidates_dir}")
    
    if not candidates_path.is_dir():
        raise ValueError(f"Path is not a directory: {candidates_dir}")
    
    # Find all markdown files in the directory
    md_files = sorted(candidates_path.glob("*.md"))
    
    if not md_files:
        raise ValueError(f"No markdown files found in: {candidates_dir}")
    
    for idx, md_file in enumerate(md_files, start=1):
        try:
            content = md_file.read_text(encoding="utf-8")
            
            # Extract word count from content if present (format: "**Word Count: N**")
            word_count_match = re.search(r'\*\*Word Count:\s*(\d+)\*\*', content)
            word_count = int(word_count_match.group(1)) if word_count_match else len(content.split())
            
            # Clean up the word count footer if present
            clean_content = re.sub(r'\n\n---\n\*\*Word Count:\s*\d+\*\*', '', content)
            
            candidate = ArticleCandidate(
                article_id=idx,
                content=clean_content.strip(),
                word_count=word_count,
                generation_timestamp=time.time()
            )
            candidates.append(candidate)
            
            if verbose:
                print(f"  Loaded: {md_file.name} ({word_count} words)")
                
        except Exception as e:
            if verbose:
                print(f"  ✗ Failed to load {md_file.name}: {e}")
            raise
    
    if verbose:
        print(f"✓ Loaded {len(candidates)} candidates from disk\n")
    
    return candidates
```

### Step 5: Update Main Pipeline Logic

**Location**: `main()` function, around line 2050-2090

**Current Logic to Replace**:
```python
# Current logic checks args.enable_synthesis to decide whether to run synthesis
if args.enable_synthesis:
    pipeline = ArticleSynthesisPipeline(verbose=args.verbose)
    result = pipeline.run(...)
```

**New Logic**:
```python
# Determine pipeline mode
candidates = None
run_synthesis = True  # Default: run full pipeline

if args.candidates_only:
    # Mode 1: Generate candidates only, skip synthesis
    run_synthesis = False
    # ... (candidate generation code runs, but synthesis is skipped)
    
elif args.candidates_dir:
    # Mode 2: Load candidates from disk, run synthesis
    candidates = load_candidate_files(args.candidates_dir, verbose=args.verbose)
    # ... (synthesis pipeline runs with loaded candidates)
    
else:
    # Mode 3: Default - Generate candidates and run full pipeline
    # ... (candidate generation code runs, synthesis runs)
```

### Step 6: Update Metrics and Output Logic

**Considerations**:
1. When `--candidates-only` is used, skip the synthesis pipeline but still print metrics summary
2. When `--candidates-dir` is used, skip candidate generation metrics but track synthesis metrics
3. Ensure output directory structure is consistent across all modes

## Command Line Interface Summary

### Usage Examples

```bash
# Mode 1: Generate candidates only (no synthesis)
python post_generator.py --topic-file my_topic.txt --iterations 10 --candidates-only --output my_article

# Mode 2: Load candidates from folder and run synthesis
python post_generator.py --topic-file my_topic.txt --candidates-dir outputs/2024-01-15/my_article/candidates --output my_article

# Mode 3: Default - Full pipeline (generate + synthesis)
python post_generator.py --topic-file my_topic.txt --iterations 10 --output my_article
```

## Backward Compatibility

### Removed Flags
- `--enable-synthesis` - Removed, synthesis now runs by default

### New Flags
- `--candidates-only` - Optional, generates candidates only
- `--candidates-dir` - Optional, loads candidates from disk

### Default Behavior Change
- **Before**: Candidates generated, synthesis only runs with `--enable-synthesis`
- **After**: Full pipeline runs by default (candidates + synthesis)

## File Changes Summary

| File | Changes |
|------|---------|
| `post_generator.py` | Remove `--enable-synthesis` flag and logic, add `--candidates-only` and `--candidates-dir` flags, add `load_candidate_files()` function, update main() pipeline logic |

## Testing Checklist

- [ ] Test `--candidates-only` flag generates candidates and skips synthesis
- [ ] Test `--candidates-dir` flag loads candidates from folder and runs synthesis
- [ ] Test default behavior runs full pipeline
- [ ] Test error handling when `--candidates-dir` folder doesn't exist
- [ ] Test error handling when `--candidates-dir` folder is empty
- [ ] Test metrics are correctly tracked for all modes
- [ ] Test output files are saved correctly for all modes
- [ ] Test backward compatibility (existing scripts without `--enable-synthesis` work)

## Implementation Order

1. Add `--candidates-only` and `--candidates-dir` argument definitions
2. Add `load_candidate_files()` function
3. Remove `--enable-synthesis` argument and validation logic
4. Update main() function to handle new modes
5. Update metrics and output logic
6. Test all modes