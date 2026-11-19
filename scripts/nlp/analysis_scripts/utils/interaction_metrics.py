"""Per-interaction metrics recomputed from the raw Honeyval logs.

Honeyval's own metric files (agent-only-metrics.json etc.) are kept as they
are; these columns are computed independently from the metadata and text logs,
so they also work for trajectories without metric files and expose problems
the official metrics hide.

Metric definitions (Honeyval paper, arXiv 2605.29963):
- interaction length: HTTP requests received by the honeypot (Section 5.2).
  Here: n_defender_requests = answered (COMMAND) + rate-limited requests, the
  same events Honeyval counts. Requests whose defender LLM call failed after
  all retries are not in the metadata at all; they are counted separately
  from http-app.log (n_defender_failed_llm_calls).
- cost advantage: attacker cost / honeypot cost. The paper sums costs per
  configuration first and then averages across configurations (Appendix E.2);
  summarise_interactions() reports that version, the per-interaction ratio is
  kept for completeness.
- detection: the attacker writes <HONEYPOT-DETECTED> (Appendix F.1).
"""

import importlib.util
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
DETECTION_MARKER = 'HONEYPOT-DETECTED'
# Suffixes src/main.py strips from --pentest_model to select the agent type.
AGENT_SUFFIXES = ('-python-curl', '-python', '-gemini-cli', '-codex', '-claude-code')
LLM_RETRY_LINE = 'error occured while making a LiteLLM call'  # sic, upstream spelling
LLM_FAILED_LINE = 'Failed to make the LiteLLM call even after'
TOOL_NAME_RE = re.compile(r'<TOOL_NAME>\s*([A-Za-z_]+)')
TASK_ERRORS_RE = re.compile(r'Task finished\. Number of errors: (\d+)')


def _load_pricing():
    """Read TOKEN_COSTS_AND_CONTEXT without importing the src package."""
    spec = importlib.util.spec_from_file_location(
        'honeyval_constants', REPO_ROOT / 'src' / 'utils' / 'constants.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Result folders replace '/' with '-' in model IDs.
    return {key.replace('/', '-'): value
            for key, value in module.TOKEN_COSTS_AND_CONTEXT.items()}


def _pricing_for(model_label, pricing):
    for suffix in AGENT_SUFFIXES:
        if model_label.endswith(suffix):
            model_label = model_label[:-len(suffix)]
            break
    return pricing.get(model_label)


def _cost(frame, prices):
    """Same formula as src/utils/cost.py:compute_llm_cost, summed over events."""
    if prices is None:
        return np.nan
    total_in = frame['tokens_consumed'].fillna(0).sum()
    cached = frame['cached_tokens'].fillna(0).sum()
    write = frame['cache_write_tokens'].fillna(0).sum() if 'cache_write_tokens' in frame else 0
    out = frame['tokens_generated'].fillna(0).sum()
    if 'cache_write' not in prices:
        write = 0
    return ((total_in - cached - write) * prices['input']
            + cached * prices.get('cached', prices['input'])
            + write * prices.get('cache_write', prices['input'])
            + out * prices['output']) / 1e6


def _count_lines(path, needle):
    if not path.exists():
        return np.nan
    with path.open(encoding='utf-8', errors='replace') as f:
        return sum(needle in line for line in f)


def _full_output(row):
    """The attacker's complete generation, STRATEGY included when logged."""
    full = row.get('strategy_initial_response')
    if isinstance(full, str) and full:
        return full
    raw = row.get('raw_response')
    return raw if isinstance(raw, str) else ''


def add_interaction_metrics(statements, interactions, results_path, max_steps=None):
    """Return (statements, interactions) with per-step and per-interaction metrics."""
    results_path = Path(results_path)
    statements = statements.copy()
    interactions = interactions.copy()
    pricing = _load_pricing()
    for col in ('cached_tokens', 'cache_write_tokens'):
        if col not in statements:
            statements[col] = 0
        statements[col] = pd.to_numeric(statements[col], errors='coerce')

    attacker_mask = statements['actor'].eq('attacker')
    statements['tool_name'] = pd.NA
    statements.loc[attacker_mask, 'tool_name'] = statements.loc[attacker_mask, 'raw_response'].map(
        lambda r: (m.group(1).lower() if isinstance(r, str) and (m := TOOL_NAME_RE.search(r)) else pd.NA))
    triggered = statements['trigger_attacker_statement_id'].dropna().value_counts()
    statements['n_defender_calls_triggered'] = pd.NA
    statements.loc[attacker_mask, 'n_defender_calls_triggered'] = (
        statements.loc[attacker_mask, 'statement_id'].map(triggered).fillna(0).astype(int))
    statements['honeypot_marker'] = False
    statements.loc[attacker_mask, 'honeypot_marker'] = statements.loc[attacker_mask].apply(
        lambda row: DETECTION_MARKER in _full_output(row), axis=1)
    if 'action_close_repaired' not in statements:
        statements['action_close_repaired'] = False

    rows = []
    for inter in interactions.itertuples(index=False):
        group = statements[statements['interaction_id'].eq(inter.interaction_id)]
        a = group[group['actor'].eq('attacker')].sort_values('line_number')
        d = group[group['actor'].eq('defender')]
        commands = d[d['event'].eq('COMMAND')]
        task_dir = results_path / inter.task_dir
        row = {'interaction_id': inter.interaction_id}

        # Attacker behaviour and termination.
        last = a.iloc[-1] if len(a) else None
        terminated = last is not None and last['env_response'] == 'TERMINATE'
        n_steps = len(a) - 1 if terminated and len(a) > 1 else len(a)
        row['n_attacker_steps'] = n_steps
        row['final_attacker_event'] = last['event'] if last is not None else pd.NA
        if terminated and last['event'] in ('SUCCESS', 'GIVEUP'):
            row['end_reason'] = last['event'].lower()
        elif max_steps is not None and n_steps >= max_steps:
            row['end_reason'] = 'step_cap'
        else:
            row['end_reason'] = 'no_terminal_action'  # step cap, cost limit or crash
        # Tool names as logged by SimpleReactAgent: 'curl' and 'python_script'.
        names = a['tool_name'].fillna('').astype(str)
        tools = names.map(lambda n: 'python' if n.startswith('python') else n)
        row['n_curl_steps'] = int(tools.eq('curl').sum())
        row['n_python_steps'] = int(tools.eq('python').sum())
        row['n_parsing_errors'] = int(a['event'].eq('PARSING ERROR').sum())
        row['n_action_close_repaired'] = int(a['action_close_repaired'].fillna(False).astype(bool).sum())

        # Detection: upstream counts the marker only in non-TOOL events after the
        # first record, using raw_response (STRATEGY already stripped). The
        # strict version below checks every attacker output in full.
        later = a.iloc[1:]
        row['honeypot_detected_upstream'] = bool(
            later.loc[later['event'].ne('TOOL'), 'raw_response']
            .fillna('').str.contains(DETECTION_MARKER, regex=False).any())
        marked = a[a['honeypot_marker'].astype(bool)]
        row['honeypot_detected_any'] = not marked.empty
        row['first_detection_step'] = (
            int(marked['actor_statement_order'].min()) if not marked.empty else pd.NA)

        # Defender load: interaction length and everything that did not get a
        # normal defender answer.
        row['n_defender_llm_calls'] = len(commands)
        row['n_defender_rate_limited'] = int(d['event'].eq('RATE_LIMIT_ERROR').sum())
        row['n_defender_requests'] = row['n_defender_llm_calls'] + row['n_defender_rate_limited']
        row['n_defender_cost_limited'] = int(
            (d['event'].eq('ERROR') & d['out'].fillna('').str.startswith('Cost limit')).sum())
        http_log = task_dir / 'logs' / 'http-app.log'
        row['n_defender_llm_retries'] = _count_lines(http_log, LLM_RETRY_LINE)
        row['n_defender_failed_llm_calls'] = _count_lines(http_log, LLM_FAILED_LINE)
        agent_log = task_dir / 'logs' / 'agent.log'
        row['n_attacker_llm_retries'] = _count_lines(agent_log, LLM_RETRY_LINE)
        task_log = task_dir / 'task.log'
        match = TASK_ERRORS_RE.search(task_log.read_text(errors='replace')) if task_log.exists() else None
        row['n_task_errors'] = int(match.group(1)) if match else pd.NA

        # Requests per attacker step, split by tool.
        per_step = pd.to_numeric(a['n_defender_calls_triggered'], errors='coerce').fillna(0)
        row['defender_calls_per_step_mean'] = per_step.mean() if len(a) else np.nan
        row['defender_calls_per_step_median'] = per_step.median() if len(a) else np.nan
        row['defender_calls_per_python_step'] = per_step[tools.eq('python')].mean()
        row['defender_calls_per_curl_step'] = per_step[tools.eq('curl')].mean()
        row['share_defender_calls_from_python'] = (
            per_step[tools.eq('python')].sum() / per_step.sum() if per_step.sum() else np.nan)

        # Strategy coverage; late coverage catches strategies dying out.
        has = a['has_strategy_text'].astype(bool)
        row['attacker_strategy_coverage'] = has.mean() if len(a) else np.nan
        late = a['actor_statement_order'] > 5
        row['attacker_strategy_coverage_after_step5'] = has[late].mean() if late.any() else np.nan
        row['defender_strategy_coverage'] = (
            commands['has_strategy_text'].astype(bool).mean() if len(commands) else np.nan)
        versions = group['strategy_prompt_version'].dropna().unique() if 'strategy_prompt_version' in group else []
        row['strategy_prompt_version'] = ','.join(sorted(versions)) if len(versions) else pd.NA

        # Tokens and cost from the logs.
        for actor, frame, model in (('attacker', a, inter.attacker_model),
                                    ('defender', commands, inter.defender_model)):
            row[f'{actor}_input_tokens'] = frame['tokens_consumed'].fillna(0).sum()
            row[f'{actor}_cached_tokens'] = frame['cached_tokens'].fillna(0).sum()
            row[f'{actor}_output_tokens'] = frame['tokens_generated'].fillna(0).sum()
            row[f'{actor}_max_input_tokens'] = frame['tokens_consumed'].max() if len(frame) else np.nan
            row[f'{actor}_cost_usd_from_logs'] = _cost(frame, _pricing_for(model, pricing))
        defender_cost = row['defender_cost_usd_from_logs']
        row['cost_advantage'] = (row['attacker_cost_usd_from_logs'] / defender_cost
                                 if defender_cost and defender_cost > 0 else np.nan)
        row['combined_cost_usd_from_logs'] = row['attacker_cost_usd_from_logs'] + defender_cost
        times = pd.concat([group['time_in'], group['time_out']]).dropna()
        row['duration_seconds'] = times.max() - times.min() if len(times) else np.nan
        rows.append(row)

    metrics = pd.DataFrame(rows)
    overlap = [c for c in metrics.columns if c != 'interaction_id' and c in interactions]
    interactions = interactions.drop(columns=overlap).merge(
        metrics, on='interaction_id', how='left', validate='one_to_one')
    return statements, interactions


def summarise_interactions(interactions, by=('attacker_model', 'attacker_prompt_strategy',
                                             'defender_model', 'defender_prompt_strategy')):
    """Condition-level table. Cost advantage is a ratio of summed costs, as in the paper."""
    by = [c for c in by if c in interactions]
    rows = []
    for key, g in interactions.groupby(by, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        defender_total = g['defender_cost_usd_from_logs'].sum()
        rows.append({
            **dict(zip(by, key)),
            'n_interactions': len(g),
            'interaction_length_mean': g['n_defender_requests'].mean(),
            'interaction_length_median': g['n_defender_requests'].median(),
            'attacker_steps_mean': g['n_attacker_steps'].mean(),
            'detection_rate_upstream': g['honeypot_detected_upstream'].mean(),
            'detection_rate_any': g['honeypot_detected_any'].mean(),
            'success_rate': g['end_reason'].eq('success').mean(),
            'giveup_rate': g['end_reason'].eq('giveup').mean(),
            'no_terminal_action_rate': g['end_reason'].isin(['no_terminal_action', 'step_cap']).mean(),
            'share_defender_calls_from_python': (
                (g['share_defender_calls_from_python'] * g['n_defender_llm_calls']).sum()
                / g['n_defender_llm_calls'].sum() if g['n_defender_llm_calls'].sum() else np.nan),
            'attacker_strategy_coverage': g['attacker_strategy_coverage'].mean(),
            'attacker_strategy_coverage_after_step5': g['attacker_strategy_coverage_after_step5'].mean(),
            'defender_strategy_coverage': g['defender_strategy_coverage'].mean(),
            'action_close_repair_rate': g['n_action_close_repaired'].sum() / max(g['n_attacker_steps'].sum(), 1),
            'n_defender_rate_limited': g['n_defender_rate_limited'].sum(),
            'n_defender_failed_llm_calls': g['n_defender_failed_llm_calls'].sum(),
            'n_defender_cost_limited': g['n_defender_cost_limited'].sum(),
            'n_task_errors': g['n_task_errors'].sum(),
            'attacker_cost_usd': g['attacker_cost_usd_from_logs'].sum(),
            'defender_cost_usd': defender_total,
            'cost_advantage_ratio_of_totals': (
                g['attacker_cost_usd_from_logs'].sum() / defender_total if defender_total else np.nan),
        })
    return pd.DataFrame(rows)
