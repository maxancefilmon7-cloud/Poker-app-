import streamlit as st
import pandas as pd
from datetime import datetime
import os
import copy
import json

# --- CONSTANTES ---
POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

st.set_page_config(page_title="Poker Pro Tracker", layout="centered")

# --- CSS ---
st.markdown("""
<style>
    .metric-pot {
        text-align: center; font-size: 24px; font-weight: bold;
        color: #facc15; background-color: #1f2937; padding: 15px;
        border-radius: 10px; border: 1px solid #374151; margin-bottom: 20px;
    }
    .metric-board {
        text-align: center; font-size: 28px; letter-spacing: 3px;
        background-color: #111827; padding: 10px; border-radius: 8px;
        margin-bottom: 20px; border: 1px solid #1f2937;
    }
    div.stButton > button { font-weight: bold; border-radius: 8px; border: 1px solid #4b5563; }
</style>
""", unsafe_allow_html=True)

# --- INITIALISATION SESSION STATE ---
defaults = {
    'step': "LOGIN",
    'username': "",
    'tournoi': "",
    'stack_actuel': 0.0,
    'bb_val': 1000.0,
    'ante': 0.0,
    'hand_data': {"pot_total": 0.0, "actions": [], "board": "", "my_cards": ""},
    'initial_players': [],
    'active_players': [],
    'hero_invested': 0.0,
    'current_bet': 0.0,
    'player_invested_street': {},
    'history': [],
    'my_pos': None,
    'is_raising': False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --- FICHIERS ---
def get_state_file():
    return f"state_{st.session_state.username}.json"

def get_csv_name():
    return f"mains_{st.session_state.username}.csv"

def get_villain_notes_file():
    # FIX : notes par utilisateur, pas globales
    return f"notes_vilains_{st.session_state.username}.csv"

def save_user_state():
    state = {
        "tournoi": st.session_state.tournoi,
        "stack_actuel": st.session_state.stack_actuel,
        "bb_val": st.session_state.bb_val,
        "ante": st.session_state.ante,
    }
    with open(get_state_file(), "w") as f:
        json.dump(state, f)

def get_user_tournaments():
    tournois = []
    file = get_csv_name()
    if os.path.exists(file):
        try:
            df = pd.read_csv(file, sep=';')
            if "Tournoi" in df.columns:
                tournois = df["Tournoi"].dropna().unique().tolist()
        except Exception:
            pass

    state_file = get_state_file()
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
            t_actuel = state.get("tournoi", "")
            if t_actuel and t_actuel not in tournois:
                tournois.append(t_actuel)
        except Exception:
            pass
    return tournois

# --- COMPOSANTS UI ---
def card_picker(label, key_suffix):
    st.write(f"**{label}**")
    v = st.segmented_control("Valeur", ["2","3","4","5","6","7","8","9","T","J","Q","K","A"], key=f"v_{key_suffix}")
    s = st.segmented_control("Couleur", ["♠️", "❤️", "♦️", "♣️"], key=f"s_{key_suffix}")
    return f"{v}{s}" if v and s else None

def get_action_order(street):
    if street == "Préflop":
        return ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    return ["SB", "BB", "UTG", "HJ", "CO", "BTN"]

def render_player_radar(current_to_act=None):
    html = '<div style="display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; margin-bottom: 25px;">'
    for p in st.session_state.initial_players:
        hero_tag = " (Toi)" if p == st.session_state.my_pos else ""
        if p not in st.session_state.active_players:
            style = "background-color: #1f2937; color: #6b7280; text-decoration: line-through; border: 1px solid #374151;"
        elif p == current_to_act:
            style = "background-color: #22c55e; color: #000000; font-weight: 900; border: 2px solid #ffffff; box-shadow: 0 0 12px #22c55e;"
        else:
            style = "background-color: #1e3a8a; color: #e0e7ff; border: 1px solid #3b82f6;"
        html += f'<div style="padding: 10px 14px; border-radius: 8px; font-size: 14px; text-align: center; {style}">{p}{hero_tag}</div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

# --- UNDO / HISTORIQUE ---
def save_state():
    state_copy = {
        'active_players': copy.deepcopy(st.session_state.active_players),
        'to_act_list': copy.deepcopy(st.session_state.to_act_list) if 'to_act_list' in st.session_state else None,
        'hand_data': copy.deepcopy(st.session_state.hand_data),
        'current_bet': st.session_state.current_bet,
        'player_invested_street': copy.deepcopy(st.session_state.player_invested_street),
        'hero_invested': st.session_state.hero_invested,
        'step': st.session_state.step,
        'stack_actuel': st.session_state.stack_actuel,
        'is_raising': st.session_state.is_raising,
    }
    st.session_state.history.append(state_copy)

def undo_action():
    if not st.session_state.history:
        return
    last = st.session_state.history.pop()
    st.session_state.active_players = last['active_players']
    if last['to_act_list'] is not None:
        st.session_state.to_act_list = last['to_act_list']
    elif 'to_act_list' in st.session_state:
        del st.session_state.to_act_list
    st.session_state.hand_data = last['hand_data']
    st.session_state.current_bet = last['current_bet']
    st.session_state.player_invested_street = last['player_invested_street']
    st.session_state.hero_invested = last['hero_invested']
    st.session_state.step = last['step']
    st.session_state.stack_actuel = last['stack_actuel']
    st.session_state.is_raising = last['is_raising']
    save_user_state()
    st.rerun()

def transition_next_street():
    st.session_state.current_bet = 0.0
    st.session_state.player_invested_street = {p: 0.0 for p in st.session_state.active_players}
    if 'to_act_list' in st.session_state:
        del st.session_state.to_act_list

def save_hand_to_csv(data: dict):
    file = get_csv_name()
    header = not os.path.exists(file)
    pd.DataFrame([data]).to_csv(file, mode='a', index=False, sep=';', header=header)

# --- BLOC D'ACTION (CŒUR DU JEU) ---
def action_block(street_name, next_step_label, next_step_state):
    board = st.session_state.hand_data['board'].strip()
    if board:
        st.markdown(f"<div class='metric-board'>{board}</div>", unsafe_allow_html=True)

    st.markdown(
        f"<div class='metric-pot'>💰 POT : {st.session_state.hand_data['pot_total']:.1f} BB"
        f"<br><span style='font-size: 14px; font-weight: normal; color: #9ca3af;'>"
        f"Mise à suivre : {st.session_state.current_bet} BB</span></div>",
        unsafe_allow_html=True
    )

    # Un seul joueur restant → victoire par fold
    if len(st.session_state.active_players) == 1:
        vainqueur = st.session_state.active_players[0]
        render_player_radar(vainqueur)
        st.success(f"🎉 Tout le monde s'est couché ! **{vainqueur}** gagne la main.")
        if st.button("💾 Enregistrer la main", type="primary", use_container_width=True):
            if vainqueur == st.session_state.my_pos:
                profit = st.session_state.hand_data['pot_total'] - st.session_state.hero_invested
            else:
                profit = -st.session_state.hero_invested
            st.session_state.stack_actuel += profit
            save_user_state()
            save_hand_to_csv({
                "Heure": datetime.now().strftime("%H:%M"),
                "Tournoi": st.session_state.tournoi,
                "Position": st.session_state.my_pos,
                "Ta Main": st.session_state.hand_data['my_cards'],
                "Gagnant": vainqueur,
                "Ton Profit": profit,
                "Nouveau Stack": st.session_state.stack_actuel,
            })
            st.session_state.step = "START_HAND"
            st.rerun()
        if st.session_state.history:
            st.divider()
            if st.button("🔙 Annuler", use_container_width=True):
                undo_action()
        return

    # Initialisation de l'ordre d'action
    if 'to_act_list' not in st.session_state:
        order = get_action_order(street_name)
        st.session_state.to_act_list = [p for p in order if p in st.session_state.active_players]

    # Tour terminé
    if len(st.session_state.to_act_list) == 0:
        render_player_radar(None)
        st.success("✅ Tour de mise terminé !")
        if st.button(f"➡️ {next_step_label}", type="primary", use_container_width=True):
            save_state()
            transition_next_street()
            st.session_state.step = next_step_state
            st.rerun()
        if st.session_state.history:
            st.divider()
            if st.button("🔙 Annuler", use_container_width=True):
                undo_action()
        return

    current_player = st.session_state.to_act_list[0]
    cost_to_call = st.session_state.current_bet - st.session_state.player_invested_street.get(current_player, 0)

    render_player_radar(current_player)

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("❌ Fold", use_container_width=True):
            save_state()
            if current_player == st.session_state.my_pos:
                profit = -st.session_state.hero_invested
                st.session_state.stack_actuel += profit
                save_user_state()
                save_hand_to_csv({
                    "Heure": datetime.now().strftime("%H:%M"),
                    "Tournoi": st.session_state.tournoi,
                    "Position": st.session_state.my_pos,
                    "Ta Main": st.session_state.hand_data['my_cards'],
                    "Gagnant": "Autre (Tu as Fold)",
                    "Ton Profit": profit,
                    "Nouveau Stack": st.session_state.stack_actuel,
                })
                st.session_state.step = "START_HAND"
                st.toast("Tu t'es couché. Main enregistrée ! 📝", icon="✅")
                st.rerun()
            else:
                st.session_state.active_players.remove(current_player)
                st.session_state.to_act_list.pop(0)
                st.session_state.hand_data['actions'].append(f"{street_name} : {current_player} Fold")
                st.session_state.is_raising = False
                st.rerun()

    with col2:
        label = "🟢 Check" if cost_to_call == 0 else f"🟡 Call ({cost_to_call:.1f})"
        if st.button(label, use_container_width=True):
            save_state()
            st.session_state.player_invested_street[current_player] = st.session_state.current_bet
            st.session_state.hand_data['pot_total'] += cost_to_call
            if current_player == st.session_state.my_pos:
                st.session_state.hero_invested += cost_to_call
            action_word = "Check" if cost_to_call == 0 else "Call"
            st.session_state.hand_data['actions'].append(f"{street_name} : {current_player} {action_word}")
            st.session_state.to_act_list.pop(0)
            st.session_state.is_raising = False
            st.rerun()

    with col3:
        if st.button("🔴 Raise", use_container_width=True):
            st.session_state.is_raising = True
            st.rerun()

    # Panneau de relance
    if st.session_state.is_raising:
        with st.container():
            st.markdown("<div style='background-color:#1e293b; padding:15px; border-radius:10px; margin-top:10px;'>", unsafe_allow_html=True)
            format_saisie = st.radio("Saisie en :", ["BB", "Jetons"], horizontal=True)

            # FIX : min_value strictement > current_bet pour forcer une vraie relance
            min_raise = float(st.session_state.current_bet) + 0.5

            if format_saisie == "BB":
                new_bet_bb = st.number_input(
                    f"Relance totale (Min : {min_raise:.1f} BB)",
                    min_value=min_raise,
                    value=min_raise,
                    step=0.5,
                )
            else:
                min_jetons = int(min_raise * st.session_state.bb_val)
                jetons = st.number_input("Relance totale en Jetons", min_value=min_jetons, step=500)
                new_bet_bb = jetons / st.session_state.bb_val
                st.info(f"Équivalent : **{new_bet_bb:.1f} BB**")

            if st.button("🔥 Valider la Relance", type="primary", use_container_width=True):
                if new_bet_bb > st.session_state.current_bet:
                    save_state()
                    cost = new_bet_bb - st.session_state.player_invested_street.get(current_player, 0)
                    st.session_state.current_bet = new_bet_bb
                    st.session_state.player_invested_street[current_player] = new_bet_bb
                    st.session_state.hand_data['pot_total'] += cost
                    if current_player == st.session_state.my_pos:
                        st.session_state.hero_invested += cost
                    st.session_state.hand_data['actions'].append(
                        f"{street_name} : {current_player} Raise à {new_bet_bb:.1f} BB"
                    )
                    order = get_action_order(street_name)
                    active_ordered = [p for p in order if p in st.session_state.active_players]
                    idx = active_ordered.index(current_player)
                    st.session_state.to_act_list = active_ordered[idx+1:] + active_ordered[:idx]
                    st.session_state.is_raising = False
                    st.rerun()
                else:
                    st.error("La relance doit être supérieure à la mise actuelle !")
            st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.history:
        st.divider()
        if st.button("🔙 Annuler l'action précédente", use_container_width=True):
            undo_action()


# ─────────────────────────────────────────────────────────────
# BARRE LATÉRALE
# ─────────────────────────────────────────────────────────────
if st.session_state.step not in ["LOGIN", "SETUP"]:
    st.sidebar.title(f"👤 {st.session_state.username}")
    app_mode = st.sidebar.radio("Navigation", ["🃏 Table de Poker", "📊 Mes Statistiques"])
    st.sidebar.divider()

    st.sidebar.metric("Stack Actuel", f"{st.session_state.stack_actuel:.1f} BB")
    st.sidebar.caption(f"📍 Tournoi : **{st.session_state.tournoi}**")

    with st.sidebar.expander("⚙️ Changer Blinds & Ante"):
        new_level = st.text_input("Nouveau niveau (ex: 1000/2000)")
        new_ante = st.radio(
            "Ante présente ?",
            ["Oui (1 BB)", "Non (0 BB)"],
            index=0 if st.session_state.ante > 0 else 1,
            horizontal=True,
        )
        if st.button("Mettre à jour"):
            try:
                if new_level:
                    parts = new_level.split('/')
                    if len(parts) != 2:
                        raise ValueError("Format invalide")
                    new_bb = float(parts[-1])
                    chips_restants = st.session_state.stack_actuel * st.session_state.bb_val
                    st.session_state.bb_val = new_bb
                    st.session_state.stack_actuel = chips_restants / new_bb
                st.session_state.ante = 1.0 if "Oui" in new_ante else 0.0
                save_user_state()
                st.sidebar.success(f"À jour ! {st.session_state.stack_actuel:.1f} BB")
                st.rerun()
            except Exception:
                st.sidebar.error("Format invalide (ex: 1000/2000)")

    st.sidebar.divider()

    # FIX : st.sidebar.divider() était dans le if block après st.rerun() → inaccessible
    if st.sidebar.button("⚙️ Gérer mes Tournois", use_container_width=True):
        st.session_state.step = "SETUP"
        st.rerun()

    st.sidebar.divider()

    # Profils Vilains — FIX : fichier per-user
    st.sidebar.subheader("🕵️ Profils Vilains")
    v_nom = st.sidebar.text_input("Pseudo du joueur")
    v_note = st.sidebar.text_area("Observation tactique")
    if st.sidebar.button("Sauvegarder la note"):
        if v_nom.strip():
            with open(get_villain_notes_file(), mode='a', encoding='utf-8-sig') as f:
                note_clean = v_note.replace(';', ',').replace('\n', ' ')
                f.write(f"{datetime.now().strftime('%d/%m %H:%M')};{v_nom.strip()};{note_clean}\n")
            st.sidebar.success("Note ajoutée !")
        else:
            st.sidebar.warning("Entre un pseudo !")

    with st.sidebar.expander("📖 Consulter mon Carnet"):
        notes_file = get_villain_notes_file()
        if os.path.exists(notes_file):
            try:
                df_notes = pd.read_csv(notes_file, sep=';', names=["Date", "Joueur", "Note"], header=None)
                if df_notes.empty:
                    st.write("Le carnet est vide.")
                else:
                    for _, row in df_notes.iterrows():
                        st.markdown(f"**👤 {row['Joueur']}** *(le {row['Date']})*")
                        st.info(f"📝 {row['Note']}")
            except Exception:
                st.write("Impossible de lire le carnet.")
        else:
            st.write("Aucune note pour le moment.")

else:
    app_mode = "🃏 Table de Poker"


# ─────────────────────────────────────────────────────────────
# MODE STATISTIQUES
# ─────────────────────────────────────────────────────────────
if app_mode == "📊 Mes Statistiques":
    st.title("📈 Tableau de Bord Analytique")
    fichier = get_csv_name()
    if os.path.exists(fichier):
        df = pd.read_csv(fichier, sep=';')
        if "Tournoi" in df.columns:
            tournois_list = df["Tournoi"].dropna().unique().tolist()
            tournoi_choisi = st.selectbox("Filtrer par tournoi", ["Global"] + tournois_list)
            if tournoi_choisi != "Global":
                df = df[df["Tournoi"] == tournoi_choisi]

        col1, col2 = st.columns(2)
        col1.metric("Mains jouées", len(df))
        col2.metric("Profit Net Total", f"{df['Ton Profit'].sum():.1f} BB")

        st.subheader("Évolution de ton Stack")
        st.line_chart(df['Nouveau Stack'])
        st.subheader("Historique Brut")
        st.dataframe(df.tail(10))
    else:
        st.warning(f"Aucune statistique pour '{st.session_state.username}'.")

# ─────────────────────────────────────────────────────────────
# MODE JEU
# ─────────────────────────────────────────────────────────────
elif app_mode == "🃏 Table de Poker":

    # LOGIN
    if st.session_state.step == "LOGIN":
        st.title("👋 Bienvenue sur Poker Pro Tracker")
        st.info("Chaque utilisateur possède son propre profil pour ses tournois et statistiques.")
        pseudo = st.text_input("Quel est ton Pseudo ?")
        if st.button("Se Connecter", type="primary", use_container_width=True):
            if pseudo.strip():
                st.session_state.username = pseudo.strip()
                if os.path.exists(get_state_file()):
                    try:
                        with open(get_state_file(), "r") as f:
                            state = json.load(f)
                        st.session_state.tournoi = state.get("tournoi", "")
                        st.session_state.stack_actuel = state.get("stack_actuel", 100.0)
                        st.session_state.bb_val = state.get("bb_val", 1000.0)
                        st.session_state.ante = state.get("ante", 0.0)
                    except Exception:
                        pass
                    st.session_state.step = "START_HAND" if st.session_state.tournoi else "SETUP"
                    if st.session_state.tournoi:
                        st.toast(f"Bon retour {pseudo} !", icon="🔄")
                else:
                    st.session_state.step = "SETUP"
                st.rerun()
            else:
                st.error("Entre un pseudo valide.")

    # SETUP
    elif st.session_state.step == "SETUP":
        st.title("🏆 Gestion des Tournois")
        mes_tournois = get_user_tournaments()
        choix = st.radio("Que veux-tu faire ?", ["Créer un nouveau", "Reprendre un existant", "Supprimer"], horizontal=True)

        if choix == "Créer un nouveau":
            nom_tournoi = st.text_input("Nom du Tournoi (ex: EPT Paris)", "Mon Tournoi")
            stack_initial = st.number_input("Stack de départ (Jetons)", value=20000, step=1000)
            level = st.text_input("Blinds (ex: 500/1000)", "500/1000")
            ante = st.radio("Ante présente ?", ["Oui (1 BB)", "Non (0 BB)"], horizontal=True)

            if st.button("Lancer ce Tournoi 🚀", type="primary", use_container_width=True):
                try:
                    bb = float(level.split('/')[-1]) if '/' in level else 1000.0
                    st.session_state.tournoi = nom_tournoi
                    st.session_state.bb_val = bb
                    st.session_state.stack_actuel = stack_initial / bb
                    st.session_state.ante = 1.0 if "Oui" in ante else 0.0
                    save_user_state()
                    st.session_state.step = "START_HAND"
                    st.session_state.history = []
                    st.rerun()
                except Exception:
                    st.error("Format de blinds invalide (ex: 500/1000)")

        elif choix == "Reprendre un existant":
            if mes_tournois:
                t_choisi = st.selectbox("Sélectionne le tournoi à reprendre", mes_tournois)

                last_bb = 0.0
                has_history = False
                file = get_csv_name()
                if os.path.exists(file):
                    try:
                        df_temp = pd.read_csv(file, sep=';')
                        # FIX : df_temp.columns et non df.columns
                        if "Tournoi" in df_temp.columns:
                            df_t = df_temp[df_temp["Tournoi"] == t_choisi]
                            if not df_t.empty:
                                last_bb = df_t.iloc[-1]["Nouveau Stack"]
                                has_history = True
                    except Exception:
                        pass

                if has_history:
                    st.success(f"✅ Reprise automatique : Tu avais **{last_bb:.1f} BB** à la fin de ta dernière main.")
                else:
                    st.info("Ce tournoi est récent, aucune main n'a encore été jouée.")

                ante = st.radio("L'Ante est-elle actuellement en jeu ?", ["Oui (1 BB)", "Non (0 BB)"], horizontal=True)

                if st.button("Reprendre la partie 🎮", type="primary", use_container_width=True):
                    st.session_state.tournoi = t_choisi
                    if has_history:
                        st.session_state.stack_actuel = last_bb
                    st.session_state.ante = 1.0 if "Oui" in ante else 0.0
                    save_user_state()
                    st.session_state.step = "START_HAND"
                    st.session_state.history = []
                    st.rerun()
            else:
                st.warning("Tu n'as aucun tournoi enregistré.")

        elif choix == "Supprimer":
            if mes_tournois:
                t_del = st.selectbox("Tournoi à supprimer définitivement", mes_tournois)
                st.error("⚠️ Cette action effacera toutes les statistiques liées à ce tournoi.")
                if st.button("🗑️ Supprimer le tournoi", use_container_width=True):
                    file = get_csv_name()
                    if os.path.exists(file):
                        try:
                            df_del = pd.read_csv(file, sep=';')
                            # FIX : df_del.columns et non df.columns
                            if "Tournoi" in df_del.columns:
                                df_del = df_del[df_del["Tournoi"] != t_del]
                                df_del.to_csv(file, index=False, sep=';')
                        except Exception:
                            st.error("Erreur lors de la suppression des données.")

                    state_file = get_state_file()
                    if os.path.exists(state_file):
                        try:
                            with open(state_file, "r") as f:
                                state = json.load(f)
                            if state.get("tournoi") == t_del:
                                state["tournoi"] = ""
                                with open(state_file, "w") as f:
                                    json.dump(state, f)
                                st.session_state.tournoi = ""
                        except Exception:
                            pass

                    st.success(f"Le tournoi '{t_del}' a été supprimé.")
                    st.rerun()
            else:
                st.info("Aucun tournoi à supprimer.")

    # NOUVELLE MAIN
    elif st.session_state.step == "START_HAND":
        st.title("🃏 Nouvelle Main")

        if st.session_state.history:
            if st.button("🔙 Oups, annuler la fin de main précédente", use_container_width=True):
                undo_action()
            st.divider()

        st.session_state.initial_players = POSITIONS[:]
        st.session_state.active_players = POSITIONS[:]
        st.session_state.my_pos = st.segmented_control("Ta Position", st.session_state.active_players)
        c1 = card_picker("Carte 1", "mc1")
        c2 = card_picker("Carte 2", "mc2")

        if st.button("Valider et Préflop ➡️", type="primary", use_container_width=True):
            if not st.session_state.my_pos:
                st.error("Sélectionne ta position !")
            elif not c1 or not c2:
                st.error("Sélectionne tes deux cartes !")
            else:
                st.session_state.hand_data = {
                    "pot_total": 1.5 + st.session_state.ante,
                    "actions": [],
                    "board": "",
                    "my_cards": f"{c1} {c2}",
                }
                st.session_state.current_bet = 1.0
                st.session_state.player_invested_street = {p: 0.0 for p in st.session_state.active_players}
                st.session_state.player_invested_street["SB"] = 0.5
                st.session_state.player_invested_street["BB"] = 1.0

                st.session_state.hero_invested = st.session_state.ante
                if st.session_state.my_pos == "SB":
                    st.session_state.hero_invested += 0.5
                elif st.session_state.my_pos == "BB":
                    st.session_state.hero_invested += 1.0

                st.session_state.history = []
                save_state()
                st.session_state.step = "PREFLOP"
                st.rerun()

    # PREFLOP
    elif st.session_state.step == "PREFLOP":
        if st.button("🔙 Corriger mes cartes / ma position"):
            st.session_state.step = "START_HAND"
            st.rerun()
        action_block("Préflop", "Tirer le Flop", "FLOP_CARDS")

    # FLOP
    elif st.session_state.step == "FLOP_CARDS":
        st.title("🌊 Le Flop")
        f1 = card_picker("Flop 1", "f1")
        f2 = card_picker("Flop 2", "f2")
        f3 = card_picker("Flop 3", "f3")
        if st.button("Valider le Board ➡️", type="primary", use_container_width=True):
            if f1 and f2 and f3:
                st.session_state.hand_data['board'] += f" {f1} {f2} {f3}"
                st.session_state.step = "FLOP"
                st.rerun()
            else:
                st.error("Sélectionne les 3 cartes du flop !")
        if st.session_state.history:
            st.divider()
            if st.button("🔙 Retour au Préflop", use_container_width=True):
                undo_action()

    elif st.session_state.step == "FLOP":
        action_block("Flop", "Tirer la Turn", "TURN_CARD")

    # TURN
    elif st.session_state.step == "TURN_CARD":
        st.title("🔥 La Turn")
        t1 = card_picker("Carte Turn", "t1")
        if st.button("Valider le Board ➡️", type="primary", use_container_width=True):
            if t1:
                st.session_state.hand_data['board'] += f" {t1}"
                st.session_state.step = "TURN"
                st.rerun()
            else:
                st.error("Sélectionne la carte Turn !")
        if st.session_state.history:
            st.divider()
            if st.button("🔙 Retour au Flop", use_container_width=True):
                undo_action()

    elif st.session_state.step == "TURN":
        action_block("Turn", "Tirer la River", "RIVER_CARD")

    # RIVER
    elif st.session_state.step == "RIVER_CARD":
        st.title("💧 La River")
        r1 = card_picker("Carte River", "r1")
        if st.button("Valider le Board ➡️", type="primary", use_container_width=True):
            if r1:
                st.session_state.hand_data['board'] += f" {r1}"
                st.session_state.step = "RIVER"
                st.rerun()
            else:
                st.error("Sélectionne la carte River !")
        if st.session_state.history:
            st.divider()
            if st.button("🔙 Retour à la Turn", use_container_width=True):
                undo_action()

    elif st.session_state.step == "RIVER":
        action_block("River", "Aller au Showdown", "RESULTAT")

    # SHOWDOWN
    elif st.session_state.step == "RESULTAT":
        board = st.session_state.hand_data['board'].strip()
        st.markdown(f"<div class='metric-board'>{board}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='metric-pot'>🏆 POT FINAL : {st.session_state.hand_data['pot_total']:.1f} BB</div>",
            unsafe_allow_html=True
        )
        st.warning(f"Ton investissement total : **{st.session_state.hero_invested:.1f} BB**")

        st.subheader("Qui remporte le pot ?")
        display_active = [
            f"{p} (Toi)" if p == st.session_state.my_pos else p
            for p in st.session_state.active_players
        ]
        gagnant = st.segmented_control("Vainqueur", display_active)

        st.write("Cartes du vainqueur (Optionnel)")
        wc1 = card_picker("Carte 1", "wc1")
        wc2 = card_picker("Carte 2", "wc2")
        cartes_gagnant = f"{wc1} {wc2}" if wc1 and wc2 else "Cachées"

        if st.button("💾 Enregistrer et rejouer", type="primary", use_container_width=True):
            if not gagnant:
                st.error("Sélectionne le vainqueur !")
            else:
                vrai_gagnant = gagnant.split(" ")[0]
                if vrai_gagnant == st.session_state.my_pos:
                    profit = st.session_state.hand_data['pot_total'] - st.session_state.hero_invested
                else:
                    profit = -st.session_state.hero_invested

                st.session_state.stack_actuel += profit
                save_user_state()
                save_hand_to_csv({
                    "Heure": datetime.now().strftime("%H:%M"),
                    "Tournoi": st.session_state.tournoi,
                    "Position": st.session_state.my_pos,
                    "Ta Main": st.session_state.hand_data['my_cards'],
                    "Gagnant": vrai_gagnant,
                    "Son Jeu": cartes_gagnant,
                    "Ton Profit": profit,
                    "Nouveau Stack": st.session_state.stack_actuel,
                })
                st.session_state.step = "START_HAND"
                st.session_state.history = []
                transition_next_street()
                st.rerun()

        if st.session_state.history:
            st.divider()
            if st.button("🔙 Annuler et revenir aux actions River", use_container_width=True):
                undo_action()
