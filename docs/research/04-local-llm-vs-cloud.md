# Local LLM (Qwen 3.5) vs Cloud (Claude) Analysis

## Qwen 3.5 Model Lineup (Feb 2026)

| Model | Total Params | Active Params | Architecture | Context | VRAM (Q4) |
|---|---|---|---|---|---|
| Qwen3.5-0.8B | 0.8B | 0.8B | Dense | 262K | ~1 GB |
| Qwen3.5-4B | 4B | 4B | Dense | 262K | ~4-6 GB |
| Qwen3.5-9B | 9B | 9B | Dense | 262K | ~8 GB |
| Qwen3.5-27B | 27B | 27B | Dense | 262K | ~20 GB |
| Qwen3.5-122B-A10B | 122B | 10B | MoE | 262K | ~73 GB |
| Qwen3.5-397B-A17B | 397B | 17B | MoE | 262K+ | ~214 GB |

All models: Apache 2.0 licensed, native tool calling, 262K context window.

## Why the 122B-A10B Model Matters

The MoE (Mixture-of-Experts) architecture activates only 10B of 122B total parameters per token. This means:
- **Much stronger reasoning** than a dense 27B model
- **Only ~73GB VRAM** needed (fits on single H100 80GB or Mac Studio Ultra 256GB)
- **Inference speed** comparable to a dense 10B model despite 122B total knowledge
- Benchmarks approach Claude Sonnet 4.6 on many tasks

## Recommended Hybrid Architecture

```
TIER 1 - LOCAL (Qwen 3.5 122B via Ollama) - 90% of volume
  Tasks: Sentiment classification, entity extraction, news summarization,
         SEC filing triage, alert generation, data normalization,
         earnings call analysis, competitor reports
  Latency: <200ms classification, ~50-80 tok/s generation
  Cost: $0 marginal (hardware amortized)

TIER 2 - CLOUD (Claude Sonnet 4.6) - 8% of volume
  Tasks: Complex filing analysis, strategy generation, nuanced
         financial reasoning where 122B falls short
  Cost: ~$270/mo at moderate volume

TIER 3 - CLOUD (Claude Opus 4.6) - 2% of volume
  Tasks: Distressed asset deep evaluation, novel situations,
         restructuring analysis, QA spot-checks of local model
  Cost: ~$50-60/mo at low volume
```

## With 122B Model: What Changes?

The 122B-A10B model significantly improves the local tier compared to the 27B:

| Capability | Qwen 27B | Qwen 122B-A10B | Claude Sonnet 4.6 |
|---|---|---|---|
| Sentiment classification | Very Good | Excellent | Excellent |
| SEC filing analysis | Good | Very Good | Excellent |
| Financial nuance/judgment | Moderate | Good-Very Good | Strong |
| Long-context reasoning | Good (262K) | Very Good (262K) | Excellent (200K) |
| Hallucination risk | Moderate | Lower | Low |

**Key impact**: Many tasks that previously required Claude Sonnet (Tier 2) can now be handled locally by the 122B model, reducing cloud API costs by ~50-70%.

## Hardware Requirements for 122B

| Option | Cost | Performance |
|---|---|---|
| H100 80GB (cloud, RunPod) | ~$2/hr ($1,440/mo 24/7) | Best performance, ~50-80 tok/s |
| Mac Studio M3 Ultra 256GB | ~$8,000-10,000 one-time | Good, ~25+ tok/s with MoE offloading |
| 2x RTX 4090 (48GB combined) | ~$4,000-5,000 one-time | Feasible with model splitting, ~30-40 tok/s |

**Recommendation**: If you can spin up a machine with Qwen 3.5 122B, it significantly reduces cloud dependency. Most filing analysis, earnings calls, and medium-complexity tasks stay local.

## Cost Comparison (With 122B)

| Approach | Monthly Cost | Quality |
|---|---|---|
| All Cloud (Claude) | $200-335 | Highest |
| Hybrid with 27B local | $160-250 | High |
| **Hybrid with 122B local** | **$100-170** | **High (closer to all-cloud)** |
| All Local (122B only) | Hardware only | Good (no frontier for edge cases) |

The 122B model saves ~$80-150/mo vs the 27B hybrid by handling Tier 2 tasks locally.

## Quality Tradeoffs for Financial Analysis

### Where 122B excels vs 27B:
- Multi-document synthesis (comparing multiple filings)
- Nuanced covenant language interpretation
- Earnings call tone analysis
- Distressed asset preliminary screening
- Complex structured output generation

### Where Claude Opus still wins:
- Novel bankruptcy situations with no historical precedent
- Complex multi-factor reasoning about restructuring outcomes
- Cases where hallucination risk must be minimized (high-stakes decisions)
- Very long documents requiring 200K+ context

## Routing Logic

```python
def route_analysis(task, document):
    if task.type in ["sentiment", "ner", "headline", "alert"]:
        return ollama("qwen3.5:122b", document)  # always local

    elif task.type in ["filing_analysis", "earnings", "report"]:
        result = ollama("qwen3.5:122b", document)  # try local first
        if result.confidence < 0.65 or task.requires_frontier_reasoning:
            result = claude("sonnet-4.6", document)  # cloud fallback
        return result

    elif task.type in ["distressed_eval", "restructuring", "novel_situation"]:
        return claude("opus-4.6", document)  # always cloud for highest stakes

    # Spot-check: 5% of local outputs verified by Opus
    if random.random() < 0.05:
        cloud_result = claude("opus-4.6", document)
        log_quality_comparison(result, cloud_result)
```
