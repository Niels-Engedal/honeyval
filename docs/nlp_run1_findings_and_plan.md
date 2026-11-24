# Run 1 findings and the plan for judge-guided prompt optimization

Status: 2026-11-24. Covers the first vulnerable-only run and the plan that follows from it. Numbers come from `results/nlp_analysis/nlp-dsabl-vs-luna-20261120-072404/` (not in git).

## 1. Run 1: `nlp-dsabl-vs-luna-20261120-072404`

**Settings**
- Attacker: `nearai/deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated-python-curl`, effort `medium`, prompt `exploit-detect`.
- Defender: `openai/gpt-6-luna`, effort `low`, instructions `vulnerable`.
- 4 apps × 10 samples, 100-step cap, honeypot rate limit 12/min.
- Cost limits per trajectory: attacker $5, defender $2.
- 1 worker, restarted with 3 workers. Trajectories that were in progress at the restart were rerun from step 0.

**Results per app**

| App | Attacker | Defender | Run time (sum) | Median steps | Median requests | Success | Gave up | Step cap | Detected |
|---|---|---|---|---|---|---|---|---|---|
| Calculator | $0.03 | $0.01 | 11 min | 4 | 4 | 10/10 | 0 | 0 | 0 |
| CreditCardService | $1.01 | $0.13 | 7.2 h | 34.5 | 36.5 | 10/10 | 0 | 0 | 0 |
| Login | $0.09 | $0.05 | 39 min | 6 | 10.5 | 9/10 | 1 | 0 | 1 |
| Recipes | $1.69 | $7.86 | 23.5 h | 58.5 | 433 | 5/10 | 3 | 2 | 3 |
| **Total** | **$2.82** | **$8.05** | | | | 85% | | | 10% |

**Takeaways**
- **Recipes accounts for 98% of the defender cost.** The attacker solves it with Python scripts that send many requests per step. The defender's history reached 380k tokens per call, and with three workers those calls hit OpenAI's 2M tokens/minute limit.
- **About 3,500 API errors, but none of them broke the run.**
  - They were OpenAI 429s (tokens per minute), which aren't billed. 1,131 `RateLimitError` lines are in our logs.
  - Almost all succeeded on retry. Only 147 requests failed for good: 145 in Recipes/4 and 2 in Recipes/6.
- **Contaminated trajectories:** keep them only with a caveat, or exclude them.
  - Recipes/4: 145 failed defender calls, so the attacker saw HTTP 500s; plus 114 honeypot rate-limit answers.
  - Recipes/3: 93 cost-limited answers after reaching the $2 cap; plus 317 honeypot rate-limit answers.
- **Detection works:** 4 detections (Recipes 0, 1 and 8; Login 6), each followed by giving up. That's 10% overall, close to the paper's ReAct numbers.
- **Strategy coverage** is 98–99% for both sides, so the v3 history fix held.
- **Cost advantage is 0.35 (attacker ÷ defender).** That's the reverse of the paper, and it comes from the long Recipes trajectories (see section 2).
- **Open question about spend:** the OpenAI bill for the period is about $16, but the logs account for $8.05. Possible causes:
  - other runs on the same account in the billing window;
  - first attempts of the trajectories rerun after the restart;
  - long-context pricing, if Luna has it. It's unconfirmed, and even doubling all 626 calls over 272k tokens adds only about $2.

  Check the OpenAI usage page by day and model.

## 2. Why the defender's cost grows faster than the attacker's

Both sides keep their full history, but:

| Recipes | Attacker | Defender |
|---|---|---|
| LLM calls | 587 (one per step) | 3,989 (one per HTTP request) |
| Average input per call | 24k tokens | 155k tokens |
| Largest input | 62k | 380k |
| Output per call | 1,821 (mostly hidden reasoning) | 744 |

1. **More calls.** Each call costs roughly its history's size, so total cost grows with the square of the number of calls. One attacker step averaged about 7 defender calls in Recipes, and about 13 for Python steps.
2. **Bigger additions per call.**
   - **Attacker:** each step adds only its visible output plus what its script printed, about 600 tokens per step in Recipes.
   - **Defender:** each call adds every full request and response, about 400 tokens each, so about 5,000 tokens per attacker step.
3. **The attacker's main cost doesn't build up.** DeepSeek's hidden reasoning is billed as output ($1.20/M) but never added to its history, so it grows linearly with steps. Its cached history costs $0.006/M.

**Consequence:** longer interactions lower the cost advantage. Interaction length and cost advantage pull in opposite directions under this design.

## 3. Revised hypothesis

The idea: use LLM-as-judge scores for enticingness and believability from run 1 to rewrite the defender instructions. Then test whether the new prompt does significantly better than the baseline on interaction length, detection rate and/or cost advantage.

**Points to address in the design**
1. **Choose one primary outcome before running anything.**
   - **Length vs cost advantage:** longer interactions lower the cost advantage (section 2).
   - **Length vs success:** withholding success lengthens interactions even without any honeypot skill.

   Proposal:
   - primary outcome: `n_defender_requests`, reported together with success, give-up and detection rates;
   - cost advantage as a secondary outcome.
2. **Detection has little statistical power.** Going from about 10% to about 3% needs roughly 190 trajectories per arm for 80% power (two-sided, α = 0.05). Interaction length is heavy-tailed (Login: median 10.5, mean 24.7). Use Mann-Whitney or log length.
3. **The judge guides the optimization; it isn't the evidence.**
   - Showing that judge scores went up after optimizing on them is circular.
   - Evidence of improvement comes from behaviour: length, detection, success.
4. **Run 1 is training data.** It can't also be the baseline for the test. Run a fresh baseline and the new prompt in one batch, with the same settings and code version.
5. **Keep `mislead` as an arm.** It's upstream's hand-written attempt at the same goal and costs cents on Login. Beating only `vulnerable` is a weak result, because that prompt was never meant to keep attackers engaged.
6. **Scope.** One attacker model, one app. The prompt may learn DeepSeek's quirks. Freeze the final prompt before the confirmatory run, and use at most 1–3 optimization rounds.

## 4. Order of work

1. **Judge** (`scripts/nlp/analysis_scripts/02_judge.py`).
   - **Input:** the strategy statements and exchanges from preprocessing.
   - **Items:**
     - defender: strategy + request + response;
     - attacker: strategy + action + the next tool output it saw.
     - Pair the defender at step t with the attacker at step t+1.
   - **Judge model:** neither Luna nor DeepSeek.
   - **What the judge sees:** the attacker's goal, but not the defender condition.
   - **Prompt:** versioned.
   - **Output:** JSON with:
     - scores for intent (from the strategy) and execution (from the output);
     - a "not addressed" option;
     - a strategy–action consistency label;
     - a quote as evidence.
   - **Caching:** responses are cached, and costs are logged.
2. **Validate the judge before spending on new runs.**
   - **Agreement with humans:** about 200–300 items rated in Potato, reported per field.
   - **Predictive validity on all 40 trajectories of run 1:**
     - do low believability scores come before detection or giving up?
     - do high enticingness scores go with longer interactions?
   - **Known groups:** the judge should rate the rule-based control (`nlp-dsabl-rulebased-control`) as less believable. A small mislead pilot on Login (10 trajectories, cents) should score differently from vulnerable.
   - If scores don't predict behaviour, stop here. Optimizing them has no reason to help.
3. **Optimizer** (`03_optimize_prompt.py`).
   - **Input:**
     - the current instructions;
     - the objective in words;
     - the best- and worst-scored defender responses, with the judge's reasons.
   - **Output:** `prompts/defender/<name>.txt`, with the source run, judge version and hash recorded.
4. **Custom defender instructions in Honeyval.**
   - In `src/main.py`:
     - add a `custom` choice to `--honeypot_additional_instructions`;
     - add a new `--honeypot_instructions_file` option.
   - Write the text and its hash to `task.log` and the metadata.
   - Use `custom-<name>` in the results folder name.
   - Extend `_INSTRUCTIONS` in the analysis loader.
   - Add a launcher question and tests.
5. **Pilot:** 10 Login trajectories with the new prompt, to see which cost column below applies.
6. **Confirmatory run on Login** in one batch:
   - arms: `vulnerable`, `mislead`, optimized;
   - 50-step cap, the same rate limit, 3–5 workers.
7. **Comparison** (`04_compare.py`). The primary test and the secondary outcomes as written down before step 6. Judge scores serve only as a mechanism check.

## 5. Cost and time for Login

Per arm. The cost depends on how long each prompt keeps the attacker engaged.

| Trajectories per arm | Like `vulnerable` ($0.014, ~4 min each) | Like Login/6 ($0.066, ~17 min) | Full 50-step cap (~$0.25, ~45–60 min; extrapolated) |
|---|---|---|---|
| 100 | $1.40 · ~2 h | $6.60 · ~10 h | ~$25 · ~1 day |
| 250 | $3.50 · ~5.5 h | $16.50 · ~24 h | ~$60 · ~3 days |

**How these were worked out**
- **Times** assume 3 workers, with container startup on top.
- **Workers:** Login's defender context stayed under 23k tokens, so 5 workers stay well under the tokens-per-minute limit and cut the times by about 40%. NEAR AI's rate limits are unknown, so watch the attacker retries.
- **Sample sizes:**
  - 100 per arm is enough for interaction length;
  - about 190–250 per arm is needed for detection.
