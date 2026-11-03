from pathlib import Path
import json
import re
import pandas as pd

KNOWN_ATTACKER_STRATEGIES = ('exploit',)  # Add new names here if used


def parse_config(config):
    for strategy in sorted(KNOWN_ATTACKER_STRATEGIES, key=len, reverse=True):
        marker = f'-m-{strategy}-'
        if marker in config:
            attacker_model, right = config.split(marker, 1)
            if '-m-' not in right:
                break
            defender_model, defender_strategy = right.rsplit('-m-', 1)
            if attacker_model and defender_model and defender_strategy:
                return dict(attacker_model=attacker_model,
                            attacker_prompt_strategy=strategy,
                            defender_model=defender_model,
                            defender_prompt_strategy=defender_strategy)
    raise ValueError(f'Unexpected configuration name: {config}')


def read_jsonl(path):
    with path.open(encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    yield lineno, item


def read_json(path):
    if path.exists():
        with path.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_honeyval(results_path):
    results_path = Path(results_path)
    if not results_path.is_dir():
        raise FileNotFoundError(results_path)

    statements = []
    interaction_rows = []
    source_paths = sorted(results_path.rglob('agent-metadata.jsonl'))
    source_paths = [p for p in source_paths if p.parent.name == 'metadata-logs']
    if not source_paths:
        raise ValueError(f'No agent-metadata.jsonl files under {results_path}')

    for attacker_log in source_paths:
        task_dir = attacker_log.parent.parent
        if task_dir.name != 'agent-vs-http-app':
            continue
        run_dir = task_dir.parent
        try:
            run = int(run_dir.name)
        except ValueError:
            continue
        app = run_dir.parent.name
        config = run_dir.parent.parent.name
        factors = parse_config(config)
        interaction_id = f'{config}|{app}|{run}'

        for actor, filename in [('attacker', 'agent-metadata.jsonl'),
                                ('defender', 'http-app-metadata.jsonl')]:
            log = attacker_log.parent / filename
            if not log.exists():
                continue
            for lineno, record in read_jsonl(log):
                # A statement is a single original log record.
                statements.append({
                    **record,
                    'config': config,
                    **factors,
                    'app': app,
                    'run': run,
                    'interaction_id': interaction_id,
                    'actor': actor,
                    'source_file': str(log.relative_to(results_path)),
                    'line_number': lineno,
                    'statement_id': f'{interaction_id}|{actor}|{lineno}',
                })

        # Use official metrics for run-level totals, rather than summing
        # individual requests (which could omit or duplicate usage).
        success = read_json(task_dir / 'exploit-metrics-agent.json')
        agent = read_json(task_dir / 'agent-only-metrics.json')
        defender = read_json(task_dir / 'http-app-only-metrics.json')
        interaction_rows.append({
            'interaction_id': interaction_id,
            'config': config,
            **factors,
            'app': app,
            'run': run,
            'agent_success': success.get('agent_success'),
            'agent_giveup': success.get('agent_giveup'),
            'callback_success': success.get('callback_success'),
            'complete': success.get('complete'),
            'attacker_rounds': agent.get('total_interaction_rounds'),
            'defender_rounds': defender.get('total_interaction_rounds'),
            'attacker_total_tokens': agent.get('total_tokens'),
            'defender_total_tokens': defender.get('total_tokens'),
            'attacker_cost_usd': agent.get('total_dollar_cost'),
            'defender_cost_usd': defender.get('total_dollar_cost'),
            'attacker_model_time_seconds': agent.get('total_interaction_time'),
            'defender_model_time_seconds': defender.get('total_interaction_time'),
        })

    df_statements = pd.DataFrame(statements)
    df_interactions = pd.DataFrame(interaction_rows)
    if df_statements.empty:
        raise ValueError('No statement records were loaded')

    for col in ['time_in', 'time_out', 'tokens_consumed', 'tokens_generated']:
        if col not in df_statements:
            df_statements[col] = pd.NA
        df_statements[col] = pd.to_numeric(df_statements[col], errors='coerce')

    df_statements = df_statements.sort_values(
        ['interaction_id', 'time_in', 'time_out', 'actor', 'line_number'],
        kind='stable', na_position='last'
    ).reset_index(drop=True)
    df_statements['statement_order'] = (
        df_statements.groupby('interaction_id').cumcount() + 1
    )
    df_statements['actor_statement_order'] = (
        df_statements.groupby(['interaction_id', 'actor']).cumcount() + 1
    )
    df_statements['exchange_id'] = pd.NA

    # A statement is an original log event with possible strategy text. START/END
    # remain in the raw dataset for provenance, but do not belong to turns.
    # A turn contains consecutive statements by one actor. An attacker turn
    # ends at the attacker action that causes one or more defender COMMANDs;
    # those defender COMMANDs form one defender turn. The pair is an exchange.
    # Trailing attacker actions form a turn and an unanswered exchange.
    df_statements['turn_id'] = pd.NA
    df_statements['exchange_id'] = pd.NA
    df_statements['turn_statement_order'] = pd.Series(pd.NA, index=df_statements.index, dtype='Int64')
    df_statements['trigger_attacker_statement_id'] = pd.NA
    turns = []
    exchanges = []

    def text_items(frame):
        return [v for v in frame['strategy'].tolist() if isinstance(v, str) and v.strip()]

    def register_turn(frame, interaction_id, actor, turn_num, exchange_id):
        if frame.empty:
            return None
        tid = f'{interaction_id}|{actor}-turn|{turn_num}'
        ids = frame['statement_id'].tolist()
        df_statements.loc[frame.index, 'turn_id'] = tid
        df_statements.loc[frame.index, 'exchange_id'] = exchange_id
        df_statements.loc[frame.index, 'turn_statement_order'] = list(range(1, len(frame) + 1))
        texts = text_items(frame)
        turns.append(dict(
            interaction_id=interaction_id, turn_id=tid, exchange_id=exchange_id,
            actor=actor, turn_order=turn_num,
            statement_ids=ids, n_statements=len(ids),
            strategies=texts, strategy_text='\n\n'.join(texts),
            time_in=frame['time_in'].min(), time_out=frame['time_out'].max(),
            events=frame['event'].tolist(),
        ))
        return tid

    for interaction_id, group in df_statements.groupby('interaction_id', sort=False):
        attacker = group[group['actor'].eq('attacker')].sort_values('actor_statement_order')
        defender = group[group['actor'].eq('defender') & group['event'].eq('COMMAND')].sort_values(['time_in', 'line_number'])

        # Match defender requests to the active attacker action. Crucially,
        # MULTIPLE defender calls may belong to the same attacker action.
        # Interval containment is the primary criterion; an overlapping
        # interval may be considered, but unmatched records are retained and
        # flagged rather than forcibly attached to the wrong action.
        matched = []
        unmatched = []
        for _, d in defender.iterrows():
            candidates = attacker[
                (attacker['time_in'] <= d['time_in']) &
                (attacker['time_out'] >= d['time_out'])
            ]
            method = 'timestamp_containment'
            if candidates.empty:
                candidates = attacker[
                    (attacker['time_in'] <= d['time_out']) &
                    (attacker['time_out'] >= d['time_in'])
                ]
                method = 'timestamp_overlap'
            if candidates.empty:
                unmatched.append(d['statement_id'])
                continue
            # Within overlapping tool actions, prefer the last started.
            a = candidates.sort_values(['time_in', 'actor_statement_order']).iloc[-1]
            matched.append((a, d, method))
            df_statements.loc[d.name, 'trigger_attacker_statement_id'] = a['statement_id']

        if unmatched:
            print(f'WARNING {interaction_id}: {len(unmatched)} unmatched defender calls: {unmatched}')

        # Group all defender responses from the same triggering action.
        # Consecutive attacker statements since the previous trigger belong
        # to the attacker turn, including parsing errors and static calls.
        grouped = {}
        for a, d, method in matched:
            grouped.setdefault(a['statement_id'], {'trigger': a, 'responses': []})['responses'].append((d, method))

        prev_order = 0
        exchange_num = 0
        for item in sorted(grouped.values(), key=lambda x: int(x['trigger']['actor_statement_order'])):
            trigger = item['trigger']
            trigger_order = int(trigger['actor_statement_order'])
            attacker_part = attacker[(attacker['actor_statement_order'] > prev_order) &
                                     (attacker['actor_statement_order'] <= trigger_order)]
            prev_order = trigger_order
            response_pairs = sorted(item['responses'], key=lambda x: (x[0]['time_in'], x[0]['line_number']))
            defender_part = df_statements.loc[[d.name for d, _ in response_pairs]].sort_values(['time_in', 'line_number'])
            exchange_num += 1
            eid = f'{interaction_id}|exchange|{exchange_num}'
            atid = register_turn(attacker_part, interaction_id, 'attacker', exchange_num, eid)
            dtid = register_turn(defender_part, interaction_id, 'defender', exchange_num, eid)
            atexts = text_items(attacker_part)
            dtexts = text_items(defender_part)
            exchanges.append(dict(
                interaction_id=interaction_id, exchange_id=eid, exchange_order=exchange_num,
                attacker_turn_id=atid, defender_turn_id=dtid,
                attacker_statement_ids=attacker_part['statement_id'].tolist(),
                defender_statement_ids=defender_part['statement_id'].tolist(),
                n_attacker_statements=len(attacker_part),
                n_defender_statements=len(defender_part),
                attacker_strategies=atexts, defender_strategies=dtexts,
                attacker_strategy_text='\n\n'.join(atexts),
                defender_strategy_text='\n\n'.join(dtexts),
                attacker_events=attacker_part['event'].tolist(),
                attacker_actions=attacker_part['action_body'].tolist(),
                defender_requests=defender_part['in'].tolist(),
                defender_outputs=defender_part['out'].tolist(),
                trigger_attacker_statement_id=trigger['statement_id'],
                response_source='defender', match_status=(
                    'timestamp_containment' if all(m == 'timestamp_containment' for _, m in response_pairs)
                    else 'timestamp_overlap'),
                time_in=attacker_part['time_in'].min(), time_out=defender_part['time_out'].max(),
                complete=True,
            ))

        # Retain trailing attacker statements as a real turn and an unanswered
        # exchange, including final GIVEUP and TERMINATE records where present.
        trailing = attacker[attacker['actor_statement_order'] > prev_order]
        if not trailing.empty:
            exchange_num += 1
            eid = f'{interaction_id}|exchange|{exchange_num}'
            atid = register_turn(trailing, interaction_id, 'attacker', exchange_num, eid)
            atexts = text_items(trailing)
            exchanges.append(dict(
                interaction_id=interaction_id, exchange_id=eid, exchange_order=exchange_num,
                attacker_turn_id=atid, defender_turn_id=None,
                attacker_statement_ids=trailing['statement_id'].tolist(), defender_statement_ids=[],
                n_attacker_statements=len(trailing), n_defender_statements=0,
                attacker_strategies=atexts, defender_strategies=[],
                attacker_strategy_text='\n\n'.join(atexts), defender_strategy_text='',
                attacker_events=trailing['event'].tolist(), attacker_actions=trailing['action_body'].tolist(),
                defender_requests=[], defender_outputs=[],
                trigger_attacker_statement_id=None, response_source='none',
                match_status='unanswered', time_in=trailing['time_in'].min(),
                time_out=trailing['time_out'].max(), complete=False,
            ))

    df_turns = pd.DataFrame(turns)
    df_exchanges = pd.DataFrame(exchanges)
    if not df_exchanges.empty:
        df_exchanges = df_exchanges.sort_values(['interaction_id', 'exchange_order']).reset_index(drop=True)
        df_exchanges['next_attacker_strategy_text'] = (
            df_exchanges.groupby('interaction_id')['attacker_strategy_text'].shift(-1)
        )

    # Add condition/application metadata to each analytical level.
    context_cols = ['interaction_id', 'config', 'app', 'run',
                    'attacker_model', 'attacker_prompt_strategy',
                    'defender_model', 'defender_prompt_strategy']
    context = df_interactions[context_cols]
    df_turns = df_turns.merge(context, on='interaction_id', how='left', validate='many_to_one')
    df_exchanges = df_exchanges.merge(context, on='interaction_id', how='left', validate='many_to_one')
    # Lifecycle records are preserved, but should be excluded from NLP samples.
    df_statements['has_strategy_text'] = df_statements['strategy'].map(
        lambda x: isinstance(x, str) and bool(x.strip())
    )

    # Compare both actors' raw records against HoneyVal's official counts.
    # This is an integrity check, independent of our reconstructed links.
    # Replicate HoneyVal SimpleReActAgent.calculate_interaction_length_stats.
    # A single-record TERMINATE log is counted as ONE round by HoneyVal;
    # for multi-record logs, only a final TERMINATE reduces the count by 1.
    # Preserve original metadata-file order (line_number), not timestamp order.
    def count_attacker_rounds(group):
        group = group.sort_values('line_number')
        n = len(group)
        if n == 0:
            return float('nan')
        last_terminates = group.iloc[-1]['env_response'] == 'TERMINATE'
        if n == 1:
            return 1 if last_terminates else float('nan')
        return n - 1 if last_terminates else n

    attacker_counts = (
        df_statements[df_statements['actor'].eq('attacker')]
        .groupby('interaction_id')
        .apply(count_attacker_rounds, include_groups=False)
        .rename('n_attacker_log_rounds')
    )
    defender_raw_counts = df_statements[
        (df_statements['actor'] == 'defender') &
        (df_statements['event'] == 'COMMAND')
    ].groupby('interaction_id').size().rename('n_defender_log_rounds')
    df_interactions = df_interactions.join(attacker_counts, on='interaction_id')
    df_interactions = df_interactions.join(defender_raw_counts, on='interaction_id')
    # A missing group in groupby means zero observed rounds, not an
    # automatic mismatch. Preserve missing official metrics as NA.
    for actor in ('attacker', 'defender'):
        actual = pd.to_numeric(
            df_interactions[f'n_{actor}_log_rounds'], errors='coerce'
        ).fillna(0)
        official = pd.to_numeric(
            df_interactions[f'{actor}_rounds'], errors='coerce'
        )
        df_interactions[f'{actor}_rounds_match_metrics'] = (
            actual.eq(official).where(official.notna(), pd.NA).astype('boolean')
        )
        df_interactions[f'{actor}_rounds_validation_status'] = [
            'metric_missing' if pd.isna(expected) else
            'match' if observed == expected else 'mismatch'
            for observed, expected in zip(actual, official)
        ]

    counts = df_statements.groupby('interaction_id').size().rename('n_statements')
    exchanges_counts = df_exchanges.groupby('interaction_id').size().rename('n_exchanges')
    defender_counts = df_exchanges.groupby('interaction_id')['n_defender_statements'].sum().rename('n_linked_defender_calls')
    df_interactions = df_interactions.join(counts, on='interaction_id')
    df_interactions = df_interactions.join(exchanges_counts, on='interaction_id')
    df_interactions = df_interactions.join(defender_counts, on='interaction_id')
    df_interactions['combined_cost_usd'] = (
        df_interactions['attacker_cost_usd'].fillna(0) +
        df_interactions['defender_cost_usd'].fillna(0)
    )

    # A discrepancy means the log or linking is incomplete. Keep the data
    # available for inspection rather than silently treating it as complete.
    mismatch = df_interactions[
        df_interactions['defender_rounds_validation_status'] == 'mismatch'
    ]
    if not mismatch.empty:
        print(f'WARNING: {len(mismatch)} genuine defender log/metric count mismatches')
    missing = df_interactions[
        df_interactions['defender_rounds_validation_status'] == 'metric_missing'
    ]
    if not missing.empty:
        print(f'INFO: {len(missing)} interactions have no comparable defender metric')
    # Missing join counts are zero observed events, not a failure by themselves.
    link_mismatch = df_interactions[
        df_interactions['n_linked_defender_calls'].fillna(0) !=
        df_interactions['n_defender_log_rounds'].fillna(0)
    ]
    if not link_mismatch.empty:
        print(f'WARNING: {len(link_mismatch)} interactions contain unlinked defender calls')

    assert df_statements['statement_id'].is_unique
    assert df_exchanges['exchange_id'].is_unique
    assert df_turns['turn_id'].is_unique
    assert df_statements.loc[df_statements['event'].eq('COMMAND') & df_statements['actor'].eq('defender'), 'turn_id'].notna().all(), 'Unlinked defender calls; inspect before analysis'
    assert df_interactions['interaction_id'].is_unique
    return df_statements, df_turns, df_exchanges, df_interactions


# Notebook usage:
# df_statements, df_exchanges, df_interactions = load_honeyval(results_path)
# display(df_exchanges[['app', 'run', 'exchange_order', 'attacker_event',
#                       'match_status', 'response_source']].head(20))
# display(df_interactions.head())
