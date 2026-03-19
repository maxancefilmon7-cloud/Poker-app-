import os
import json
import copy
import psycopg2
import psycopg2.extras
import pandas as pd
from datetime import datetime
from io import BytesIO
from functools import wraps
from flask import (
    Flask, render_template, request, session,
    jsonify, send_file
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
DATABASE_URL = os.environ.get('POSTGRES_URL', '')

# ---------------------------------------------------------------------------
# DB helpers — Postgres obligatoire (pas de fallback mémoire)
# ---------------------------------------------------------------------------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError('Base de données non configurée. Ajoute POSTGRES_URL dans les variables Vercel.')
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        print('⚠️  POSTGRES_URL absent — base de données requise pour fonctionner.')
        return
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS game_state (
                        username TEXT PRIMARY KEY,
                        state JSONB DEFAULT '{}',
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS hands (
                        id SERIAL PRIMARY KEY,
                        username TEXT,
                        tournament TEXT,
                        heure TEXT,
                        position TEXT,
                        my_cards TEXT,
                        board TEXT DEFAULT '',
                        winner TEXT,
                        winner_cards TEXT,
                        actions JSONB DEFAULT '[]',
                        is_favorite BOOLEAN DEFAULT FALSE,
                        profit REAL,
                        new_stack REAL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS villain_notes (
                        id SERIAL PRIMARY KEY,
                        username TEXT,
                        player_name TEXT,
                        note TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)
                # Migration colonnes pour tables existantes
                for col_sql in [
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS board TEXT DEFAULT ''",
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS actions JSONB DEFAULT '[]'",
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN DEFAULT FALSE",
                ]:
                    cur.execute(col_sql)
            conn.commit()
    except Exception as e:
        print(f'init_db error: {e}')


def load_state(username):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SELECT state FROM game_state WHERE username=%s', (username,))
                row = cur.fetchone()
                if row and row['state']:
                    d = default_state()
                    d.update(dict(row['state']))
                    return d
    except Exception as e:
        print(f'load_state error: {e}')
    return default_state()


def persist_state(username, state):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO game_state (username, state, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (username) DO UPDATE
                        SET state = EXCLUDED.state,
                            updated_at = EXCLUDED.updated_at
                """, (username, json.dumps(state)))
            conn.commit()
    except Exception as e:
        print(f'persist_state error: {e}')


def default_state():
    return {
        'step': 'SETUP',
        'tournoi': '',
        'stack_actuel': 0.0,
        'bb_val': 1000.0,
        'ante': 0.0,
        'hand_data': {'pot_total': 0.0, 'actions': [], 'board': '', 'my_cards': ''},
        'initial_players': ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
        'active_players': ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
        'hero_invested': 0.0,
        'current_bet': 0.0,
        'player_invested_street': {},
        'history': [],
        'my_pos': None,
        'is_raising': False,
        'to_act_list': None,
    }


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

POSITIONS = ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB']


def get_action_order(street):
    if street == 'Préflop':
        return ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    return ['SB', 'BB', 'UTG', 'HJ', 'CO', 'BTN']


def _snapshot(state):
    return {
        'active_players': copy.deepcopy(state['active_players']),
        'to_act_list': copy.deepcopy(state.get('to_act_list')),
        'hand_data': copy.deepcopy(state['hand_data']),
        'current_bet': state['current_bet'],
        'player_invested_street': copy.deepcopy(state['player_invested_street']),
        'hero_invested': state['hero_invested'],
        'step': state['step'],
        'stack_actuel': state['stack_actuel'],
        'is_raising': state.get('is_raising', False),
    }


def _restore_snapshot(state, snap):
    state['active_players'] = snap['active_players']
    state['to_act_list'] = snap['to_act_list']
    state['hand_data'] = snap['hand_data']
    state['current_bet'] = snap['current_bet']
    state['player_invested_street'] = snap['player_invested_street']
    state['hero_invested'] = snap['hero_invested']
    state['step'] = snap['step']
    state['stack_actuel'] = snap['stack_actuel']
    state['is_raising'] = snap.get('is_raising', False)


def _save_hand_db(username, state, winner, winner_cards, profit):
    hand = {
        'username': username,
        'tournament': state['tournoi'],
        'heure': datetime.now().strftime('%H:%M'),
        'position': state['my_pos'],
        'my_cards': state['hand_data']['my_cards'],
        'board': state['hand_data'].get('board', '').strip(),
        'winner': winner,
        'winner_cards': winner_cards,
        'actions': state['hand_data'].get('actions', []),
        'profit': profit,
        'new_stack': state['stack_actuel'],
        'created_at': datetime.now().isoformat(),
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO hands
                        (username, tournament, heure, position, my_cards,
                         board, winner, winner_cards, actions, profit, new_stack)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    hand['username'], hand['tournament'], hand['heure'],
                    hand['position'], hand['my_cards'], hand['board'],
                    hand['winner'], hand['winner_cards'],
                    json.dumps(hand['actions']),
                    hand['profit'], hand['new_stack'],
                ))
            conn.commit()
    except Exception as e:
        print(f'_save_hand_db error: {e}')


def _reset_to_start_hand(state):
    """Reset hand-specific fields, keeping tournament info."""
    state['step'] = 'START_HAND'
    state['hand_data'] = {'pot_total': 0.0, 'actions': [], 'board': '', 'my_cards': ''}
    state['active_players'] = list(state['initial_players'])
    state['hero_invested'] = 0.0
    state['current_bet'] = 0.0
    state['player_invested_street'] = {}
    state['history'] = []
    state['my_pos'] = None
    state['is_raising'] = False
    state['to_act_list'] = None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('username'):
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'Username requis'}), 400
    session['username'] = username
    state = load_state(username)
    return jsonify(state)


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/state', methods=['GET'])
@require_auth
def get_state():
    username = session['username']
    state = load_state(username)
    return jsonify(state)


@app.route('/api/tournaments', methods=['GET'])
@require_auth
def get_tournaments():
    username = session['username']
    state = load_state(username)
    tournaments = []
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT DISTINCT tournament FROM hands WHERE username=%s AND tournament IS NOT NULL ORDER BY tournament',
                    (username,)
                )
                tournaments = [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f'get_tournaments error: {e}')
    # include current tournament if not already in list
    current = state.get('tournoi', '')
    if current and current not in tournaments:
        tournaments.append(current)
    return jsonify({'tournaments': tournaments, 'current': current})


@app.route('/api/tournament/create', methods=['POST'])
@require_auth
def tournament_create():
    username = session['username']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Nom de tournoi requis'}), 400
    try:
        stack = float(data.get('stack', 0))
        level = str(data.get('level', '500/1000'))
        ante = float(data.get('ante', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Paramètres invalides'}), 400

    # parse level "SB/BB"
    parts = level.replace(',', '/').split('/')
    try:
        bb_val = float(parts[-1]) if len(parts) >= 2 else float(parts[0])
    except ValueError:
        bb_val = 1000.0

    ante_chips = bb_val * ante  # ante=1 => 1 BB, ante=0 => 0

    state = default_state()
    state['step'] = 'START_HAND'
    state['tournoi'] = name
    state['stack_actuel'] = stack
    state['bb_val'] = bb_val
    state['ante'] = ante_chips
    persist_state(username, state)
    return jsonify(state)


@app.route('/api/tournament/resume', methods=['POST'])
@require_auth
def tournament_resume():
    username = session['username']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Nom de tournoi requis'}), 400
    ante = float(data.get('ante', 0))

    last_stack = None
    last_bb = 1000.0
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT new_stack FROM hands
                    WHERE username=%s AND tournament=%s
                    ORDER BY created_at DESC LIMIT 1
                """, (username, name))
                row = cur.fetchone()
                if row:
                    last_stack = row[0]
    except Exception as e:
        print(f'tournament_resume error: {e}')

    state = load_state(username)
    # If we had a previous state for this tournament, keep bb_val
    if state.get('tournoi') == name:
        last_bb = state.get('bb_val', 1000.0)

    state['step'] = 'START_HAND'
    state['tournoi'] = name
    state['bb_val'] = last_bb
    state['ante'] = last_bb * ante if ante else 0.0
    if last_stack is not None:
        state['stack_actuel'] = last_stack

    _reset_to_start_hand(state)
    state['tournoi'] = name
    state['bb_val'] = last_bb
    state['ante'] = last_bb * ante if ante else 0.0
    if last_stack is not None:
        state['stack_actuel'] = last_stack

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/tournament/delete', methods=['POST'])
@require_auth
def tournament_delete():
    username = session['username']
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Nom requis'}), 400
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM hands WHERE username=%s AND tournament=%s',
                    (username, name)
                )
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    state = load_state(username)
    if state.get('tournoi') == name:
        state = default_state()
        persist_state(username, state)
    return jsonify({'ok': True, 'state': state})


@app.route('/api/tournament/update-blinds', methods=['POST'])
@require_auth
def tournament_update_blinds():
    username = session['username']
    data = request.get_json(force=True)
    level = str(data.get('level', '500/1000'))
    ante = float(data.get('ante', 0))

    parts = level.replace(',', '/').split('/')
    try:
        bb_val = float(parts[-1]) if len(parts) >= 2 else float(parts[0])
    except ValueError:
        return jsonify({'error': 'Niveau invalide'}), 400

    state = load_state(username)
    old_bb = state.get('bb_val', 1000.0)
    if old_bb > 0:
        stack_in_bb = state['stack_actuel'] / old_bb
        state['stack_actuel'] = round(stack_in_bb * bb_val)
    state['bb_val'] = bb_val
    # Si ante envoyé explicitement, l'utiliser; sinon recalculer selon l'état actuel
    if ante:
        state['ante'] = bb_val * ante
    else:
        state['ante'] = bb_val if state.get('ante', 0) > 0 else 0.0
    persist_state(username, state)
    return jsonify(state)


@app.route('/api/hand/start', methods=['POST'])
@require_auth
def hand_start():
    username = session['username']
    data = request.get_json(force=True)
    my_pos = data.get('my_pos')
    c1 = data.get('c1', '')
    c2 = data.get('c2', '')

    if not my_pos or my_pos not in POSITIONS:
        return jsonify({'error': 'Position invalide'}), 400

    state = load_state(username)

    # Deduct ante from stack if applicable
    ante = state.get('ante', 0.0)
    bb_val = state.get('bb_val', 1000.0)

    # Reset hand
    state['my_pos'] = my_pos
    state['active_players'] = list(state['initial_players'])
    state['hero_invested'] = 0.0
    state['current_bet'] = 0.0
    state['player_invested_street'] = {}
    state['is_raising'] = False
    state['history'] = []

    pot = 0.0
    # Antes
    if ante > 0:
        num_players = len(state['active_players'])
        pot += ante * num_players
        state['stack_actuel'] -= ante

    # Blinds: SB = bb_val/2, BB = bb_val
    sb_val = round(bb_val / 2)
    pot += sb_val + bb_val

    invested_street = {}
    invested_street['SB'] = sb_val
    invested_street['BB'] = bb_val

    if my_pos == 'SB':
        state['hero_invested'] = sb_val
        state['stack_actuel'] -= sb_val
    elif my_pos == 'BB':
        state['hero_invested'] = bb_val
        state['stack_actuel'] -= bb_val

    state['current_bet'] = bb_val
    state['player_invested_street'] = invested_street

    my_cards = f'{c1}{c2}' if c1 and c2 else ''
    state['hand_data'] = {
        'pot_total': pot,
        'actions': [],
        'board': '',
        'my_cards': my_cards,
    }

    # Build preflop to-act list (active players in order, skip SB/BB who already posted, start from UTG)
    order = get_action_order('Préflop')
    active = state['active_players']
    to_act = [p for p in order if p in active]
    state['to_act_list'] = to_act
    state['step'] = 'PREFLOP'

    # Save snapshot
    state['history'] = [_snapshot(state)]

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/fold', methods=['POST'])
@require_auth
def action_fold():
    username = session['username']
    data = request.get_json(force=True)
    street = data.get('street', 'Préflop')

    state = load_state(username)
    state['history'].append(_snapshot(state))

    to_act = state.get('to_act_list') or []
    current_actor = to_act[0] if to_act else None
    my_pos = state['my_pos']

    if current_actor == my_pos:
        # Hero folds — record and end hand
        profit = -state['hero_invested']
        state['stack_actuel'] = state['stack_actuel']  # already deducted
        _save_hand_db(username, state, 'Villain', '', profit)
        _reset_to_start_hand(state)
    else:
        # Villain folds
        if current_actor and current_actor in state['active_players']:
            state['active_players'].remove(current_actor)
        if to_act:
            to_act.pop(0)
        state['to_act_list'] = to_act

        # Record action
        state['hand_data']['actions'].append(f'{current_actor}: Fold ({street})')

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/call', methods=['POST'])
@require_auth
def action_call():
    username = session['username']
    data = request.get_json(force=True)
    street = data.get('street', 'Préflop')

    state = load_state(username)
    state['history'].append(_snapshot(state))

    to_act = state.get('to_act_list') or []
    current_actor = to_act[0] if to_act else None
    my_pos = state['my_pos']
    current_bet = state['current_bet']
    invested = state['player_invested_street']

    already_invested = invested.get(current_actor, 0.0)
    cost_to_call = max(0.0, current_bet - already_invested)

    if cost_to_call > 0:
        state['hand_data']['pot_total'] += cost_to_call
        invested[current_actor] = current_bet
        if current_actor == my_pos:
            state['hero_invested'] += cost_to_call
            state['stack_actuel'] -= cost_to_call

    action_label = 'Call' if cost_to_call > 0 else 'Check'
    state['hand_data']['actions'].append(f'{current_actor}: {action_label} ({street})')
    state['player_invested_street'] = invested

    if to_act:
        to_act.pop(0)
    state['to_act_list'] = to_act

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/raise', methods=['POST'])
@require_auth
def action_raise():
    username = session['username']
    data = request.get_json(force=True)
    street = data.get('street', 'Préflop')
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Montant invalide'}), 400

    state = load_state(username)

    if amount <= state['current_bet']:
        return jsonify({'error': f'Le raise doit être > {state["current_bet"]}'}), 400

    state['history'].append(_snapshot(state))

    to_act = state.get('to_act_list') or []
    current_actor = to_act[0] if to_act else None
    my_pos = state['my_pos']
    invested = state['player_invested_street']

    already_invested = invested.get(current_actor, 0.0)
    total_put_in = amount
    cost = total_put_in - already_invested

    state['hand_data']['pot_total'] += cost
    invested[current_actor] = total_put_in
    if current_actor == my_pos:
        state['hero_invested'] += cost
        state['stack_actuel'] -= cost

    state['current_bet'] = amount
    state['player_invested_street'] = invested
    state['hand_data']['actions'].append(f'{current_actor}: Raise {amount} ({street})')
    state['is_raising'] = False

    # Rebuild to_act_list: everyone except raiser who is still active
    order = get_action_order(street)
    active = state['active_players']
    raiser_idx = order.index(current_actor) if current_actor in order else -1
    # Players after raiser in order + players before raiser who haven't folded, excluding raiser
    if raiser_idx >= 0:
        new_order = order[raiser_idx + 1:] + order[:raiser_idx]
        to_act_new = [p for p in new_order if p in active and p != current_actor]
    else:
        if to_act:
            to_act.pop(0)
        to_act_new = to_act

    state['to_act_list'] = to_act_new

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/next-street', methods=['POST'])
@require_auth
def action_next_street():
    username = session['username']
    data = request.get_json(force=True)
    next_step = data.get('next_step', '')

    state = load_state(username)
    state['history'].append(_snapshot(state))

    state['current_bet'] = 0.0
    state['player_invested_street'] = {}
    state['is_raising'] = False

    # Steps that show card input before action
    card_steps = {'FLOP_CARDS', 'TURN_CARD', 'RIVER_CARD', 'RESULTAT'}
    action_steps = {'FLOP', 'TURN', 'RIVER'}

    state['step'] = next_step

    if next_step in action_steps:
        order = get_action_order(next_step.capitalize() if next_step != 'FLOP' else 'Flop')
        # Use post-flop order
        order = get_action_order('Flop')
        active = state['active_players']
        state['to_act_list'] = [p for p in order if p in active]

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/set-cards', methods=['POST'])
@require_auth
def action_set_cards():
    username = session['username']
    data = request.get_json(force=True)
    cards = data.get('cards', [])
    next_step = data.get('next_step', '')

    state = load_state(username)
    state['history'].append(_snapshot(state))

    board = state['hand_data'].get('board', '')
    new_cards = ' '.join(c for c in cards if c)
    if board:
        board = board + ' ' + new_cards
    else:
        board = new_cards
    state['hand_data']['board'] = board.strip()

    state['current_bet'] = 0.0
    state['player_invested_street'] = {}
    state['is_raising'] = False

    state['step'] = next_step

    if next_step in ('FLOP', 'TURN', 'RIVER'):
        order = get_action_order('Flop')
        active = state['active_players']
        state['to_act_list'] = [p for p in order if p in active]

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/fold-winner', methods=['POST'])
@require_auth
def action_fold_winner():
    username = session['username']
    state = load_state(username)
    state['history'].append(_snapshot(state))

    active = state['active_players']
    if len(active) == 1:
        winner = active[0]
        pot = state['hand_data']['pot_total']
        my_pos = state['my_pos']
        if winner == my_pos:
            profit = pot - state['hero_invested']
            state['stack_actuel'] += pot
        else:
            profit = -state['hero_invested']

        _save_hand_db(username, state, winner, '', profit)
        _reset_to_start_hand(state)
    else:
        return jsonify({'error': 'Plusieurs joueurs encore actifs'}), 400

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/hand/save', methods=['POST'])
@require_auth
def hand_save():
    username = session['username']
    data = request.get_json(force=True)
    winner = data.get('winner', '')
    winner_cards = data.get('winner_cards', '')

    state = load_state(username)
    my_pos = state['my_pos']
    pot = state['hand_data']['pot_total']

    if winner == my_pos:
        profit = pot - state['hero_invested']
        state['stack_actuel'] += pot
    else:
        profit = -state['hero_invested']

    _save_hand_db(username, state, winner, winner_cards, profit)
    _reset_to_start_hand(state)

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/undo', methods=['POST'])
@require_auth
def undo():
    username = session['username']
    state = load_state(username)
    history = state.get('history', [])
    if not history:
        return jsonify({'error': 'Rien à annuler'}), 400

    snap = history.pop()
    _restore_snapshot(state, snap)
    state['history'] = history

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/hand/favorite', methods=['POST'])
@require_auth
def toggle_favorite():
    username = session['username']
    data = request.get_json(force=True)
    hand_id = data.get('id')         # id DB (int) ou None si mémoire
    hand_idx = data.get('idx')       # index dans _mem_hands
    favorite = bool(data.get('favorite'))

    if not hand_id:
        return jsonify({'error': 'id requis'}), 400
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE hands SET is_favorite=%s WHERE id=%s AND username=%s",
                    (favorite, hand_id, username)
                )
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'ok': True, 'favorite': favorite})


@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    username = session['username']
    tournament = request.args.get('tournament', '')
    fav_only = request.args.get('favorites') == '1'

    rows = []
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if tournament and fav_only:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite
                        FROM hands
                        WHERE username=%s AND tournament=%s AND is_favorite = TRUE
                        ORDER BY created_at ASC
                    """, (username, tournament))
                elif tournament:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite
                        FROM hands
                        WHERE username=%s AND tournament=%s
                        ORDER BY created_at ASC
                    """, (username, tournament))
                elif fav_only:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite
                        FROM hands
                        WHERE username=%s AND is_favorite = TRUE
                        ORDER BY created_at ASC
                    """, (username,))
                else:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite
                        FROM hands
                        WHERE username=%s
                        ORDER BY created_at ASC
                    """, (username,))
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f'get_stats DB error: {e}')

    total_profit = sum(r.get('profit') or 0 for r in rows)
    total_hands = len(rows)

    # Stack history for chart
    stack_history = []
    for r in rows:
        stack_history.append({
            'heure': r.get('heure', ''),
            'stack': r.get('new_stack', 0),
            'tournament': r.get('tournament', ''),
        })

    # Get distinct tournaments
    tournaments_in_data = list({r['tournament'] for r in rows if r.get('tournament')})

    # 20 dernières mains (plus récentes en premier)
    last_hands = list(reversed(rows[-20:]))

    # Serialize + normalise actions
    for r in last_hands:
        if hasattr(r.get('created_at'), 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()
        # actions peut être un str JSON (depuis Postgres) ou déjà une liste
        if isinstance(r.get('actions'), str):
            try: r['actions'] = json.loads(r['actions'])
            except: r['actions'] = []
        if r.get('actions') is None:
            r['actions'] = []
        r['is_favorite'] = bool(r.get('is_favorite', False))

    return jsonify({
        'hands': last_hands,
        'tournaments': sorted(tournaments_in_data),
        'total_hands': total_hands,
        'total_profit': total_profit,
        'stack_history': stack_history,
    })


@app.route('/api/history', methods=['GET'])
@require_auth
def get_history():
    username = session['username']
    tournament = request.args.get('tournament', '')
    fav_only = request.args.get('favorites') == '1'

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                base = """
                    SELECT id, tournament, heure, position, my_cards,
                           board, winner, winner_cards, actions, profit,
                           new_stack, is_favorite, created_at
                    FROM hands WHERE username=%s
                """
                params = [username]
                if tournament:
                    base += " AND tournament=%s"
                    params.append(tournament)
                if fav_only:
                    base += " AND is_favorite = TRUE"
                base += " ORDER BY created_at DESC"
                cur.execute(base, params)
                rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            if hasattr(r.get('created_at'), 'isoformat'):
                r['created_at'] = r['created_at'].isoformat()
            if isinstance(r.get('actions'), str):
                try: r['actions'] = json.loads(r['actions'])
                except: r['actions'] = []
            if r.get('actions') is None:
                r['actions'] = []
            r['is_favorite'] = bool(r.get('is_favorite', False))

        return jsonify({'hands': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export', methods=['GET'])
@require_auth
def export_excel():
    username = session['username']
    tournament = request.args.get('tournament', '')

    rows = []
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if tournament:
                    cur.execute("""
                        SELECT id, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack, created_at
                        FROM hands
                        WHERE username=%s AND tournament=%s
                        ORDER BY created_at ASC
                    """, (username, tournament))
                else:
                    cur.execute("""
                        SELECT id, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack, created_at
                        FROM hands
                        WHERE username=%s
                        ORDER BY created_at ASC
                    """, (username,))
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Construit un DataFrame lisible avec les actions explodées
    export_rows = []
    for r in rows:
        actions = r.get('actions') or []
        if isinstance(actions, str):
            try: actions = json.loads(actions)
            except: actions = []
        export_rows.append({
            'Heure':        r.get('heure', ''),
            'Tournoi':      r.get('tournament', ''),
            'Position':     r.get('position', ''),
            'Mes cartes':   r.get('my_cards', ''),
            'Board':        r.get('board', ''),
            'Gagnant':      r.get('winner', ''),
            'Cartes gagnant': r.get('winner_cards', ''),
            'Profit (jetons)': r.get('profit', 0),
            'Nouveau stack': r.get('new_stack', 0),
            'Actions détaillées': ' | '.join(actions) if actions else '',
        })

    df = pd.DataFrame(export_rows) if export_rows else pd.DataFrame()

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Mains')
        # Ajuste la largeur des colonnes
        ws = writer.sheets['Mains']
        for col in ws.columns:
            max_len = max((len(str(c.value)) for c in col if c.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 80)

    buf.seek(0)
    filename = f'poker_{username}_{tournament or "all"}.xlsx'
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@app.route('/api/villain-notes', methods=['GET'])
@require_auth
def get_villain_notes():
    username = session['username']
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, player_name, note, created_at
                    FROM villain_notes
                    WHERE username=%s
                    ORDER BY created_at DESC
                """, (username,))
                notes = [dict(r) for r in cur.fetchall()]
        for n in notes:
            if hasattr(n.get('created_at'), 'isoformat'):
                n['created_at'] = n['created_at'].isoformat()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'notes': notes})


@app.route('/api/villain-notes', methods=['POST'])
@require_auth
def save_villain_note():
    username = session['username']
    data = request.get_json(force=True)
    player_name = (data.get('player_name') or '').strip()
    note = (data.get('note') or '').strip()
    if not player_name:
        return jsonify({'error': 'Nom du joueur requis'}), 400

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO villain_notes (username, player_name, note)
                    VALUES (%s, %s, %s)
                """, (username, player_name, note))
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'ok': True})


init_db()

handler = app

if __name__ == '__main__':
    app.run(debug=True)
