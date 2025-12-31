# Marketing Blog Post Generator

AI-powered marketing blog post generation tool with multi-stage quality synthesis pipeline.

## Quick Start

```bash
# Install dependencies
pipenv install

# Setup configuration
cp .env.example .env  # Add your API keys here

# Generate a blog post
python post_generator.py --topic-file prompts/my_topic.txt --output my_article
```

## What It Does

Generates high-quality marketing blog posts through a 6-stage pipeline:
### Multiple article generation
1. **CANDIDATES** - Generate multiple article drafts (in parallel if desired)
### Synthesis stages
2. **EXTRACT** - Convert articles into structured data cards
3. **SCORE** - Evaluate quality across 7 dimensions
4. **SELECT** - Pick the best elements from each candidate
5. **SYNTHESIZE** - Combine into a final article
6. **VALIDATE** - Verify quality and retry if needed

## Configuration

### Setup Your Models (`models.yaml`)

Define your LLM providers and create named presets:

```yaml
providers:
  local:
    base_url: "http://192.168.8.90:42069/v1"
    api_key_env: "LOCAL_API_KEY"
    models:
      - minimax-m2.1
      - qwen3-vl-30b-inst

  openai:
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    models:
      - gpt-4o

presets:
  local-minimax:
    provider: local
    model: minimax-m2.1
    description: "Local vLLM server with MiniMax"

  openai-4o:
    provider: openai
    model: gpt-4o
    description: "OpenAI GPT-4o"

default_preset: local-minimax
```

### Add API Keys (`.env`)

```env
LOCAL_API_KEY=your_key_here
OPENAI_API_KEY=sk-your-key-here
```

## Common Usage Patterns

### List Available Models

```bash
python post_generator.py --list-models
```

### Generate One Article (Default Settings)

```bash
python post_generator.py \
  --topic-file prompts/my_topic.txt \
  --output my_article
```

### Generate Multiple Candidates, Then Synthesize

```bash
# Create 5 candidates in parallel
python post_generator.py \
  --topic-file prompts/my_topic.txt \
  --output article_batch \
  --iterations 5 \
  --parallel
```

### Use Different Models for Different Stages

```bash
# Use 3 different models for candidates, then one model for synthesis
python post_generator.py \
  --candidate-presets local-qwen,local-minimax,openai-4o \
  --pipeline-preset local-qwen \
  --topic-file prompts/my_topic.txt \
  --iterations 6 \
  --parallel
```

This generates 2 candidates per model (6 total), then uses `local-qwen` for analysis and synthesis.

### Generate Candidates Only (Review Before Synthesis)

```bash
python post_generator.py \
  --topic-file prompts/my_topic.txt \
  --output candidates_for_review \
  --iterations 3 \
  --candidates-only
```

### Run Synthesis on Existing Candidates

```bash
python post_generator.py \
  --candidates-dir outputs/2024-01-15/candidates_for_review \
  --output final_article
```

### Use Pairwise Scoring for Better Consistency

```bash
python post_generator.py \
  --candidates-dir outputs/2024-01-15/my_candidates \
  --output final_article \
  --scoring-mode pairwise \
  --parallel
```

## Key Options

### Model Selection
- `--candidate-presets` - Models for candidate generation (comma-separated)
- `--pipeline-preset` - Model for analysis/synthesis stages
- `--list-models` - Show all available presets

### Generation Control
- `--iterations N` - Generate N candidate articles
- `--temperature 0.7` - Creativity (higher = more creative)
- `--target-word-count 1500` - Target article length
- `--topic-file path.txt` - File containing your topic/idea

### Pipeline Control
- `--candidates-only` - Skip synthesis, just generate candidates
- `--candidates-dir path/` - Load candidates from folder instead of generating
- `--scoring-mode absolute|pairwise` - How to evaluate quality
- `--synthesis-votes 5` - Number of scoring votes (absolute mode)

### Performance
- `--parallel` - Generate candidates concurrently
- `--max-concurrent 5` - Max parallel LLM requests
- `--verbose` - Show detailed progress

### Other
- `--filter-think` - Remove `<think>` tags from output
- `--cleanup-old 30` - Delete output folders older than 30 days

## Output Structure

```
outputs/
└── 2025-12-30/
    └── my_article/
        ├── my_article_FINAL.md                      # Final synthesized article
        ├── my_article_validation.json                # Quality validation report
        ├── my_article_pipeline_artifacts.json        # All intermediate data
        └── candidates/
            ├── my_article_candidate_01_local-qwen.md
            ├── my_article_candidate_02_local-minimax.md
            └── my_article_candidate_03_openai-4o.md
```

Filenames include the model preset name so you can see which LLM generated each candidate.

## Quality Scoring Criteria

Articles are evaluated on 7 dimensions:

| Criterion | Weight | What It Measures |
|-----------|--------|------------------|
| Hook Strength | 15% | Opening impact and curiosity |
| Argument Clarity | 20% | Clear, focused core message |
| Evidence Quality | 15% | Supporting data and examples |
| Structural Coherence | 15% | Logical flow and organization |
| Originality | 15% | Fresh angle vs. generic advice |
| Memorability | 10% | Quotable phrases and sticky ideas |
| Actionability | 10% | Clear next steps for readers |

## Scoring Modes

**Absolute Mode (default)**: Each article scored 1-10 per criterion, multiple votes averaged.
- Best for: Small candidate sets (2-5 articles)
- Use `--synthesis-votes` to control consistency

**Pairwise Mode**: Articles compared head-to-head ("Which has a stronger hook?").
- Best for: Larger sets (5-10 articles), maximum consistency
- More LLM calls, but more stable rankings
- Use `--scoring-mode pairwise`

## Advanced Examples

### High-Volume Batch Generation

```bash
python post_generator.py \
  --candidate-presets local-qwen,local-minimax \
  --pipeline-preset local-qwen \
  --topic-file prompts/my_topic.txt \
  --iterations 10 \
  --parallel \
  --max-concurrent 10 \
  --synthesis-votes 3 \
  --verbose
```

### Custom Temperature and Length

```bash
python post_generator.py \
  --topic-file prompts/my_topic.txt \
  --temperature 0.8 \
  --target-word-count 2000 \
  --output creative_article
```

### Pairwise Scoring with Parallel Processing

```bash
python post_generator.py \
  --candidates-dir outputs/2025-12-30/my_candidates \
  --scoring-mode pairwise \
  --parallel \
  --max-concurrent 10 \
  --output final_article \
  --verbose
```

## Reference Files

The tool uses context files from `reference_context/`:
- `writing_style-enhanced.md` - Writing style guidelines
- `construkted_context.md` - Company mission and context
- `Combined_Small_Team_Geospatial_Market_Analysis.md` - Market research

Pipeline stage prompts in `prompts/`:
- `pipeline_stage2_extract_system.md` - Extract structured cards
- `pipeline_stage3_score_system.md` - Absolute scoring
- `pipeline_stage3_pairwise_system.md` - Pairwise comparison
- `pipeline_stage4_select_system.md` - Element selection
- `pipeline_stage5_synthesize_system.md` - Final synthesis
- `pipeline_stage6_validate_system.md` - Quality validation

## Troubleshooting

**API Errors**: Check your API keys in `.env` and endpoints in `models.yaml`

**Out of Memory**: Reduce `--max-concurrent` or `--iterations`

**Low Quality Output**: Try:
- Different model presets
- `--scoring-mode pairwise` for better selection
- More `--synthesis-votes` for consistency
- Higher `--iterations` for more candidates

**Slow Performance**: Enable `--parallel` and increase `--max-concurrent`

---

Internal project for Construkted Reality marketing content generation.
