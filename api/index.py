import os
import json
import copy
import random
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

# ---------------------------------------------------------------------------
# Equity calculator — ranges par position + Monte Carlo
# ---------------------------------------------------------------------------
#
# MODIFIER LES RANGES ICI :
#   - VILLAIN_RANGES : ce que le vilain peut avoir selon sa position (open raise)
#   - HERO_RANGES    : ta range d'open selon ta position (pour analyse hors jeu)
#
# Format des mains :
#   'AA'  = paire (toutes couleurs)
#   'AKs' = suited (même couleur)
#   'AKo' = offsuit (couleurs différentes)
# ---------------------------------------------------------------------------

# ── RANGES VILAIN (open raise par position, 9-max) ──────────────────────────
VILLAIN_RANGES = {
    'UTG':    ['AA','KK','QQ','JJ','TT','AKs','AQs','AJs','ATs','KQs',
               'AKo','AQo'],
    'UTG+1':  ['AA','KK','QQ','JJ','TT','99','AKs','AQs','AJs','ATs','A9s',
               'KQs','KJs','AKo','AQo','AJo'],
    'UTG+2':  ['AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs',
               'A9s','A8s','KQs','KJs','QJs','AKo','AQo','AJo','ATo'],
    'MP':     ['AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs',
               'A9s','A8s','KQs','KJs','KTs','QJs','AKo','AQo','AJo','ATo'],
    'MP+1':   ['AA','KK','QQ','JJ','TT','99','88','77','AKs','AQs','AJs',
               'ATs','A9s','A8s','A7s','KQs','KJs','KTs','QJs','QTs','JTs',
               'AKo','AQo','AJo','ATo','KQo'],
    'HJ':     ['AA','KK','QQ','JJ','TT','99','88','77','AKs','AQs','AJs',
               'ATs','A9s','A8s','A7s','A6s','KQs','KJs','KTs','K9s','QJs',
               'QTs','JTs','T9s','AKo','AQo','AJo','ATo','KQo','KJo'],
    'CO':     ['AA','KK','QQ','JJ','TT','99','88','77','66','AKs','AQs',
               'AJs','ATs','A9s','A8s','A7s','A6s','A5s','KQs','KJs','KTs',
               'K9s','QJs','QTs','Q9s','JTs','J9s','T9s','98s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
    'BTN':    ['AA','KK','QQ','JJ','TT','99','88','77','66','55','44',
               'AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','A4s',
               'A3s','A2s','KQs','KJs','KTs','K9s','K8s','QJs','QTs','Q9s',
               'JTs','J9s','T9s','T8s','98s','97s','87s','76s','65s',
               'AKo','AQo','AJo','ATo','A9o','A8o','KQo','KJo','KTo','QJo','QTo','JTo'],
    'SB':     ['AA','KK','QQ','JJ','TT','99','88','77','66','55','AKs',
               'AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','KQs','KJs',
               'KTs','K9s','QJs','QTs','JTs','T9s','98s','87s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
    'BB':     ['AA','KK','QQ','JJ','TT','99','88','77','66','55','44','33',
               '22','AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s',
               'A4s','A3s','A2s','KQs','KJs','KTs','K9s','K8s','QJs','QTs',
               'Q9s','JTs','J9s','T9s','98s','87s','76s','65s','54s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
}

# ── RANGES HERO (ta range d'open par position, 9-max) ───────────────────────
HERO_RANGES = {
    'UTG':    ['AA','KK','QQ','JJ','TT','AKs','AQs','AJs','ATs','KQs',
               'AKo','AQo'],
    'UTG+1':  ['AA','KK','QQ','JJ','TT','99','AKs','AQs','AJs','ATs','A9s',
               'KQs','KJs','AKo','AQo','AJo'],
    'UTG+2':  ['AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs',
               'A9s','A8s','KQs','KJs','QJs','AKo','AQo','AJo','ATo'],
    'MP':     ['AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs',
               'A9s','A8s','KQs','KJs','KTs','QJs','AKo','AQo','AJo','ATo'],
    'MP+1':   ['AA','KK','QQ','JJ','TT','99','88','77','AKs','AQs','AJs',
               'ATs','A9s','A8s','A7s','KQs','KJs','KTs','QJs','QTs','JTs',
               'AKo','AQo','AJo','ATo','KQo'],
    'HJ':     ['AA','KK','QQ','JJ','TT','99','88','77','AKs','AQs','AJs',
               'ATs','A9s','A8s','A7s','A6s','KQs','KJs','KTs','K9s','QJs',
               'QTs','JTs','T9s','AKo','AQo','AJo','ATo','KQo','KJo'],
    'CO':     ['AA','KK','QQ','JJ','TT','99','88','77','66','AKs','AQs',
               'AJs','ATs','A9s','A8s','A7s','A6s','A5s','KQs','KJs','KTs',
               'K9s','QJs','QTs','Q9s','JTs','J9s','T9s','98s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
    'BTN':    ['AA','KK','QQ','JJ','TT','99','88','77','66','55','44',
               'AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','A4s',
               'A3s','A2s','KQs','KJs','KTs','K9s','K8s','QJs','QTs','Q9s',
               'JTs','J9s','T9s','T8s','98s','97s','87s','76s','65s',
               'AKo','AQo','AJo','ATo','A9o','A8o','KQo','KJo','KTo','QJo','QTo','JTo'],
    'SB':     ['AA','KK','QQ','JJ','TT','99','88','77','66','55','AKs',
               'AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','KQs','KJs',
               'KTs','K9s','QJs','QTs','JTs','T9s','98s','87s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
    'BB':     ['AA','KK','QQ','JJ','TT','99','88','77','66','55','44','33',
               '22','AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s',
               'A4s','A3s','A2s','KQs','KJs','KTs','K9s','K8s','QJs','QTs',
               'Q9s','JTs','J9s','T9s','98s','87s','76s','65s','54s',
               'AKo','AQo','AJo','ATo','A9o','KQo','KJo','QJo'],
}

_SUITS = 'cdhs'
_RANKS = '23456789TJQKA'

def _hand_to_combos(hand_str):
    """Convertit 'AKs', 'QQ', 'AKo' en liste de tuples (card1, card2)."""
    combos = []
    if len(hand_str) == 2:  # Paire ex: 'AA'
        r = hand_str[0]
        for i in range(len(_SUITS)):
            for j in range(i + 1, len(_SUITS)):
                combos.append((f'{r}{_SUITS[i]}', f'{r}{_SUITS[j]}'))
    elif hand_str.endswith('s'):  # Suited ex: 'AKs'
        r1, r2 = hand_str[0], hand_str[1]
        for s in _SUITS:
            combos.append((f'{r1}{s}', f'{r2}{s}'))
    elif hand_str.endswith('o'):  # Offsuit ex: 'AKo'
        r1, r2 = hand_str[0], hand_str[1]
        for s1 in _SUITS:
            for s2 in _SUITS:
                if s1 != s2:
                    combos.append((f'{r1}{s1}', f'{r2}{s2}'))
    return combos

def _run_equity(hero_cards_str, villain_pos, n_sims=4000, custom_villain_ranges=None):
    """Monte Carlo equity: hero_cards_str ex 'AhKd', villain_pos ex 'BTN'."""
    try:
        from treys import Card, Evaluator
    except ImportError:
        return {'error': 'treys non installé'}

    evaluator = Evaluator()

    # Parse hero cards (format: 'AhKd' → ['Ah', 'Kd'])
    if len(hero_cards_str) < 4:
        return {'error': 'Cartes hero invalides'}
    hero_strs = [hero_cards_str[:2], hero_cards_str[2:4]]
    try:
        hero = [Card.new(c) for c in hero_strs]
    except Exception:
        return {'error': f'Cartes hero invalides: {hero_cards_str}'}

    hero_set = set(hero_strs)

    # Construire la range adverse (custom en priorité, sinon défaut)
    ranges_source = custom_villain_ranges if custom_villain_ranges else VILLAIN_RANGES
    range_def = ranges_source.get(villain_pos) or VILLAIN_RANGES.get(villain_pos, VILLAIN_RANGES['BTN'])
    all_combos = []
    for h in range_def:
        all_combos.extend(_hand_to_combos(h))

    # Filtrer combos qui utilisent les cartes du hero
    valid_combos = [(c1, c2) for c1, c2 in all_combos
                    if c1 not in hero_set and c2 not in hero_set]

    if not valid_combos:
        return {'error': 'Aucune combo valide dans la range'}

    # Deck complet
    full_deck_strs = [f'{r}{s}' for r in _RANKS for s in _SUITS]

    wins = ties = losses = 0

    for _ in range(n_sims):
        villain_strs = random.choice(valid_combos)
        used_strs = set(hero_strs) | set(villain_strs)

        remaining = [s for s in full_deck_strs if s not in used_strs]
        random.shuffle(remaining)
        board_strs = remaining[:5]

        try:
            villain = [Card.new(c) for c in villain_strs]
            board = [Card.new(c) for c in board_strs]
            hero_rank = evaluator.evaluate(board, hero)
            villain_rank = evaluator.evaluate(board, villain)
        except Exception:
            continue

        if hero_rank < villain_rank:
            wins += 1
        elif hero_rank == villain_rank:
            ties += 1
        else:
            losses += 1

    total = wins + ties + losses
    if total == 0:
        return {'error': 'Simulation échouée'}

    return {
        'win': round(wins / total * 100, 1),
        'tie': round(ties / total * 100, 1),
        'lose': round(losses / total * 100, 1),
        'villain_pos': villain_pos,
        'range_hands': len(range_def),
        'simulations': total,
    }

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
# ---------------------------------------------------------------------------
# DB helpers — Postgres obligatoire (pas de fallback mémoire)
# ---------------------------------------------------------------------------

def get_db():
    db_url = (os.environ.get('POSTGRES_URL') or
              os.environ.get('DATABASE_URL') or
              os.environ.get('DATABASE_PUBLIC_URL', ''))
    if not db_url:
        raise RuntimeError('Base de données non configurée. Ajoute DATABASE_URL dans les variables Railway.')
    if 'sslmode' not in db_url:
        # URL interne Railway (railway.internal) = pas de SSL
        if 'railway.internal' in db_url:
            db_url += ('&sslmode=disable' if '?' in db_url else '?sslmode=disable')
        else:
            db_url += ('&sslmode=require' if '?' in db_url else '?sslmode=require')
    return psycopg2.connect(db_url)


def init_db():
    db_url = (os.environ.get('POSTGRES_URL') or
              os.environ.get('DATABASE_URL') or
              os.environ.get('DATABASE_PUBLIC_URL', ''))
    if not db_url:
        print('⚠️  DATABASE_URL absent — base de données requise pour fonctionner.')
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
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS small_blind REAL",
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS big_blind REAL",
                    "ALTER TABLE hands ADD COLUMN IF NOT EXISTS stack_start REAL",
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
        'allin_players': [],
    }


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

# Ordre complet des sièges (toutes tailles de table)
PREFLOP_SEAT_ORDER  = ['UTG', 'UTG+1', 'UTG+2', 'UTG+3', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
POSTFLOP_SEAT_ORDER = ['SB', 'BB', 'UTG', 'UTG+1', 'UTG+2', 'UTG+3', 'MP', 'MP+1', 'HJ', 'CO', 'BTN']


def get_action_order(street, active_players=None):
    order = PREFLOP_SEAT_ORDER if street == 'Préflop' else POSTFLOP_SEAT_ORDER
    if active_players:
        return [p for p in order if p in active_players]
    return order


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
        'allin_players': copy.deepcopy(state.get('allin_players', [])),
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
    state['allin_players'] = snap.get('allin_players', [])


def _filter_to_act(state, to_act):
    """Exclut les all-in du to_act_list."""
    allin = set(state.get('allin_players', []))
    return [p for p in to_act if p not in allin]


def _is_showdown_locked(state):
    """True si plus aucune decision n'est possible.
    - 0 joueur peut encore agir, OU
    - 1 seul joueur peut agir mais il a deja call la mise courante
      (donc rien a decider face a des adversaires all-in)."""
    active = state.get('active_players', [])
    if len(active) < 2:
        return False
    allin = set(state.get('allin_players', []))
    can_act = [p for p in active if p not in allin]
    if len(can_act) == 0:
        return True
    if len(can_act) == 1:
        invested = state.get('player_invested_street', {}) or {}
        current_bet = state.get('current_bet', 0) or 0
        p = can_act[0]
        return invested.get(p, 0) >= current_bet
    return False


def _save_hand_db(username, state, winner, winner_cards, profit):
    bb_val = float(state.get('bb_val') or 0)
    sb_val = round(bb_val / 2) if bb_val else None
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
        'small_blind': sb_val,
        'big_blind': bb_val if bb_val else None,
        'stack_start': state.get('stack_start'),
        'created_at': datetime.now().isoformat(),
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO hands
                        (username, tournament, heure, position, my_cards,
                         board, winner, winner_cards, actions, profit, new_stack,
                         small_blind, big_blind, stack_start)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    hand['username'], hand['tournament'], hand['heure'],
                    hand['position'], hand['my_cards'], hand['board'],
                    hand['winner'], hand['winner_cards'],
                    json.dumps(hand['actions']),
                    hand['profit'], hand['new_stack'],
                    hand['small_blind'], hand['big_blind'], hand['stack_start'],
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
    state['allin_players'] = []


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

_db_ready = False

@app.before_request
def ensure_db():
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True

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

    if not my_pos:
        return jsonify({'error': 'Position invalide'}), 400

    # Le frontend peut envoyer la liste complète des joueurs selon la taille de table
    players = data.get('players')

    state = load_state(username)

    # Mettre à jour initial_players si le frontend envoie la liste
    if players and isinstance(players, list) and len(players) >= 2:
        state['initial_players'] = players

    # Stack saisi à chaque nouvelle main (snapshot avant deductions)
    try:
        manual_stack = data.get('stack')
        if manual_stack is not None and manual_stack != '':
            state['stack_actuel'] = float(manual_stack)
    except (TypeError, ValueError):
        pass
    state['stack_start'] = state['stack_actuel']

    # Deduct ante from stack if applicable
    ante = state.get('ante', 0.0)
    bb_val = state.get('bb_val', 1000.0)

    # Snapshot AVANT de modifier l'état → undo revient à START_HAND
    pre_hand_snap = {
        'step': 'START_HAND',
        'active_players': copy.deepcopy(state.get('initial_players', [])),
        'to_act_list': [],
        'hand_data': {'pot_total': 0.0, 'actions': [], 'board': '', 'my_cards': ''},
        'current_bet': 0.0,
        'player_invested_street': {},
        'hero_invested': 0.0,
        'stack_actuel': state['stack_actuel'],
        'is_raising': False,
    }

    # Reset hand
    state['my_pos'] = my_pos
    state['active_players'] = list(state['initial_players'])
    state['hero_invested'] = 0.0
    state['current_bet'] = 0.0
    state['player_invested_street'] = {}
    state['is_raising'] = False
    state['history'] = []
    state['allin_players'] = []

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
        'actions': [f'__pot__:Préflop:{int(round(pot))}'],
        'board': '',
        'my_cards': my_cards,
    }

    # Build preflop to-act list
    active = state['active_players']
    order = get_action_order('Préflop', active)
    state['to_act_list'] = order
    state['step'] = 'PREFLOP'

    # History: snapshot PRÉ-main en premier pour pouvoir revenir à START_HAND
    state['history'] = [pre_hand_snap]

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
        to_act = _filter_to_act(state, to_act)
        if _is_showdown_locked(state):
            to_act = []
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
    to_act = _filter_to_act(state, to_act)
    if _is_showdown_locked(state):
        to_act = []
    state['to_act_list'] = to_act

    persist_state(username, state)
    return jsonify(state)


@app.route('/api/action/raise', methods=['POST'])
@require_auth
def action_raise():
    username = session['username']
    data = request.get_json(force=True)
    street = data.get('street', 'Préflop')
    is_allin = bool(data.get('allin'))
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Montant invalide'}), 400

    state = load_state(username)

    if not is_allin and amount <= state['current_bet']:
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

    # Pour un short all-in, on ne baisse pas la mise courante
    state['current_bet'] = max(state['current_bet'], amount)
    state['player_invested_street'] = invested
    label = 'All-in' if is_allin else 'Raise'
    state['hand_data']['actions'].append(f'{current_actor}: {label} {amount} ({street})')
    state['is_raising'] = False

    if is_allin:
        allin = list(state.get('allin_players', []))
        if current_actor not in allin:
            allin.append(current_actor)
        state['allin_players'] = allin
        if current_actor == my_pos:
            state['stack_actuel'] = 0.0

    # Rebuild to_act_list: everyone except raiser who is still active
    active = state['active_players']
    order = get_action_order(street, active)
    raiser_idx = order.index(current_actor) if current_actor in order else -1
    # Players after raiser in order + players before raiser who haven't folded, excluding raiser
    if raiser_idx >= 0:
        new_order = order[raiser_idx + 1:] + order[:raiser_idx]
        to_act_new = [p for p in new_order if p in active and p != current_actor]
    else:
        if to_act:
            to_act.pop(0)
        to_act_new = to_act

    to_act_new = _filter_to_act(state, to_act_new)
    if _is_showdown_locked(state):
        to_act_new = []
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

    # Enregistre le pot au debut de la nouvelle street (marker synthétique)
    street_name_map = {
        'FLOP_CARDS': 'Flop', 'FLOP': 'Flop',
        'TURN_CARD': 'Turn', 'TURN': 'Turn',
        'RIVER_CARD': 'River', 'RIVER': 'River',
    }
    new_street = street_name_map.get(next_step)
    if new_street:
        pot_now = state['hand_data'].get('pot_total', 0)
        state['hand_data']['actions'].append(f'__pot__:{new_street}:{int(round(pot_now))}')

    state['step'] = next_step

    if next_step in action_steps:
        active = state['active_players']
        new_order = get_action_order('Flop', active)
        new_order = _filter_to_act(state, new_order)
        if _is_showdown_locked(state):
            new_order = []
        state['to_act_list'] = new_order

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
        active = state['active_players']
        new_order = get_action_order('Flop', active)
        new_order = _filter_to_act(state, new_order)
        if _is_showdown_locked(state):
            new_order = []
        state['to_act_list'] = new_order

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


@app.route('/api/hand/delete', methods=['POST'])
@require_auth
def delete_hand():
    username = session['username']
    data = request.get_json(force=True)
    hand_id = data.get('id')
    if not hand_id:
        return jsonify({'error': 'id requis'}), 400
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM hands WHERE id=%s AND username=%s',
                    (hand_id, username)
                )
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})


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
                               created_at, is_favorite, small_blind, big_blind, stack_start
                        FROM hands
                        WHERE username=%s AND tournament=%s AND is_favorite = TRUE
                        ORDER BY created_at ASC
                    """, (username, tournament))
                elif tournament:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite, small_blind, big_blind, stack_start
                        FROM hands
                        WHERE username=%s AND tournament=%s
                        ORDER BY created_at ASC
                    """, (username, tournament))
                elif fav_only:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite, small_blind, big_blind, stack_start
                        FROM hands
                        WHERE username=%s AND is_favorite = TRUE
                        ORDER BY created_at ASC
                    """, (username,))
                else:
                    cur.execute("""
                        SELECT id, username, tournament, heure, position, my_cards,
                               board, winner, winner_cards, actions, profit, new_stack,
                               created_at, is_favorite, small_blind, big_blind, stack_start
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
                           new_stack, is_favorite, created_at,
                           small_blind, big_blind, stack_start
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


@app.route('/api/equity', methods=['POST'])
@require_auth
def calc_equity():
    username = session['username']
    data = request.get_json(force=True)
    my_cards = data.get('my_cards', '')
    villain_pos = data.get('villain_pos', 'BTN')
    if not my_cards or len(my_cards) < 4:
        return jsonify({'error': 'Cartes manquantes'}), 400
    state = load_state(username)
    custom_villain = state.get('custom_ranges', {}).get('villain')
    result = _run_equity(my_cards, villain_pos, custom_villain_ranges=custom_villain)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/ranges', methods=['GET'])
@require_auth
def get_ranges():
    username = session['username']
    state = load_state(username)
    custom = state.get('custom_ranges', {})
    return jsonify({
        'villain': custom.get('villain', VILLAIN_RANGES),
        'hero':    custom.get('hero',    HERO_RANGES),
        'defaults': {'villain': VILLAIN_RANGES, 'hero': HERO_RANGES},
    })


@app.route('/api/ranges', methods=['POST'])
@require_auth
def save_ranges():
    username = session['username']
    data = request.get_json(force=True)
    range_type = data.get('type')   # 'villain' ou 'hero'
    position   = data.get('position')
    hands      = data.get('hands')  # liste ex: ['AA','KK','AKs',...]
    if range_type not in ('villain', 'hero') or not position or hands is None:
        return jsonify({'error': 'Paramètres invalides'}), 400
    state = load_state(username)
    if 'custom_ranges' not in state:
        state['custom_ranges'] = {}
    if range_type not in state['custom_ranges']:
        state['custom_ranges'][range_type] = {}
    state['custom_ranges'][range_type][position] = hands
    persist_state(username, state)
    return jsonify({'ok': True, 'position': position, 'type': range_type, 'hands': len(hands)})


@app.route('/api/ranges/reset', methods=['POST'])
@require_auth
def reset_ranges():
    username = session['username']
    data = request.get_json(force=True)
    range_type = data.get('type')
    position   = data.get('position')
    state = load_state(username)
    custom = state.get('custom_ranges', {})
    if range_type and position:
        custom.get(range_type, {}).pop(position, None)
    elif range_type:
        custom.pop(range_type, None)
    else:
        custom.clear()
    state['custom_ranges'] = custom
    persist_state(username, state)
    return jsonify({'ok': True})


if __name__ == '__main__':
    app.run(debug=True)
