import time
import socket
import asyncio
import re
import os
import codecs

# ==========================================
# 1. SÉCURITÉ : ATTENTE DU PONT WINE
# ==========================================
print("Initialisation du conteneur... En attente du pont Wine (Port 18812)...")
def wait_for_port(port, host='127.0.0.1', timeout=120):
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"✅ Pont Wine prêt (Port {port}) ! Démarrage du bot...")
                return
        except OSError:
            time.sleep(1)
            if time.time() - start_time > timeout:
                raise TimeoutError("Le serveur de pont n'a pas démarré à temps.")

# On bloque l'exécution ici tant que Wine n'est pas prêt
wait_for_port(18812)

# ==========================================
# 2. IMPORTS ET CONFIGURATION
# ==========================================
from mt5linux import MetaTrader5
from telethon import TelegramClient, events

# --- TES IDENTIFIANTS (À REMPLIR SOIGNEUSEMENT) ---
API_ID = 31338024                  # Ton API ID Telegram (chiffres)
API_HASH = '0fc2cc219431f076dbd4a591c6265b44'         # Ton API Hash Telegram (entre guillemets)
MT5_LOGIN = 5048322818              # Ton numéro de compte MT5 (chiffres)
MT5_PASSWORD = '1qL*AeHs' # Ton mot de passe MT5 (entre guillemets)
MT5_SERVER = 'MetaQuotes-Demo'      # Le nom exact du serveur broker
PRIVATE_CHANNEL_ID = -1003862678081        # Nom du canal Telegram

# --- STRATÉGIE ---
SYMBOL = "XAUUSD"
LOT_SIZE = 0.02
MAX_DISTANCE = 1.5                # Décalage max toléré (1.5$ sur l'Or)

# --- SL/TP PROVISOIRES (en attente du Message 3) ---
# Sur XAUUSD, 1 pip = 0.10 pt de prix
PROV_SL_PIPS = 40                 # SL provisoire : 40 pips = 4.00 pts
PROV_TP1_PIPS = 30                # TP1 provisoire : 30 pips = 3.00 pts
PROV_TP2_PIPS = 100               # TP2 provisoire : 100 pips = 10.00 pts
PIP_SIZE = 0.10                   # Valeur d'un pip sur XAUUSD

# Initialisation MT5 (maintenant que le port est ouvert, ça passera direct)
mt = MetaTrader5()
active_trades = {}

# ==========================================
# 3. CŒUR DU BOT
# ==========================================
# Fonction de surveillance qui tourne "à côté"
async def monitor_button():
    while True:
        info = mt.terminal_info()
        if info:
            status = "VERT ✅" if info.trade_allowed else "ROUGE ❌"
            print(f"📊 État du bouton AlgoTrading : {status}")
        await asyncio.sleep(30) # 30 secondes suffisent pour ne pas polluer l'écran

async def start_bot():
    print("🔌 Connexion au compte MetaTrader 5...")
    authorized = mt.initialize(
        path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        login=MT5_LOGIN, 
        password=MT5_PASSWORD, 
        server=MT5_SERVER,
        portable=True,
        timeout=60000
    )

    if not authorized:
        print(f"❌ Erreur MT5 : {mt.last_error()}")
        return
    
    print(f"✅ Connecté avec succès à MT5 : {MT5_LOGIN}")
    
    # --- LA MAGIE EST ICI ---
    # On lance la surveillance en arrière-plan sans bloquer la suite
    asyncio.create_task(monitor_button())
    
    # Maintenant, on peut lancer Telegram normalement !
    print("🤖 Bot 100% Opérationnel. En attente de signaux sur Telegram...")
    
    client = TelegramClient('session_docker', API_ID, API_HASH)
    
    bot_state = {
        "step": 0,
        "type": None,
        "entry_price": 0.0
    }

    @client.on(events.NewMessage(chats=PRIVATE_CHANNEL_ID))
    async def handler(event):
        msg = event.raw_text.upper()
        
        if msg.strip() == "TEST":
            print("📡 Log: Message TEST reçu avec succès depuis le canal !")
            return
            
        # --- CAS 1 : FERMETURE MANUELLE TP3 ---
        if "TP3 MANUEL" in msg:
            positions = mt.positions_get(symbol=SYMBOL)
            if positions:
                for pos in positions:
                    if pos.comment == "TP3":
                        close_position(pos)
                print("✅ Positions TP3 fermées manuellement.")
            return

        # --- CAS 2 : MACHINE A ETATS ---
        try:
            # S'il y a un mot-clé de réinitialisation/départ
            if "ACHAT" in msg and "XAUUSD" in msg and "NOW" in msg:
                bot_state["step"] = 1
                bot_state["type"] = mt.ORDER_TYPE_BUY
                print("🔔 [ETAPE 1] Signal ACHAT NOW reconnu. Attente du prix d'entrée (Msg 2)...")
                return
            elif "VENTE" in msg and "XAUUSD" in msg and "NOW" in msg:
                bot_state["step"] = 1
                bot_state["type"] = mt.ORDER_TYPE_SELL
                print("🔔 [ETAPE 1] Signal VENTE NOW reconnu. Attente du prix d'entrée (Msg 2)...")
                return
                
            if bot_state["step"] == 1:
                # Cherche le premier nombre de 4 chiffres (prix de l'or > 1000)
                prices_full = re.findall(r'\b\d{4}(?:\.\d+)?\b', msg)
                if prices_full:
                    entry_signal = float(prices_full[0])
                    bot_state["entry_price"] = entry_signal
                    order_type = bot_state["type"]
                    
                    # --- VÉRIFICATION DU PRIX (SLIPPAGE) ---
                    mt.symbol_select(SYMBOL, True)
                    mt.copy_rates_from_pos(SYMBOL, mt.TIMEFRAME_M1, 0, 1)
                    tick = mt.symbol_info_tick(SYMBOL)
                
                    if tick is None or tick.ask == 0:
                        print(f"❌ Erreur : Prix invalide (0.0) pour {SYMBOL}.")
                        time.sleep(1)
                        tick = mt.symbol_info_tick(SYMBOL)
                        if tick is None or tick.ask == 0:
                            bot_state["step"] = 0 # reset
                            return

                    current_price = tick.ask if order_type == mt.ORDER_TYPE_BUY else tick.bid
                    
                    if abs(current_price - entry_signal) > MAX_DISTANCE:
                        print(f"⚠️ SIGNAL REJETÉ : Prix actuel trop éloigné ({current_price} vs signal à {entry_signal})")
                        bot_state["step"] = 0
                        return
                    
                    print(f"🚀 [ETAPE 2] Exécution immédiate : {SYMBOL} à {current_price}...")
                    
                    # --- OUVERTURE CONTOURNEMENT ECN (OUVRIR A 0) ---
                    targets = ["TP1", "TP2", "TP3"]
                    bot_state["tickets"] = []

                    for comment in targets:
                        request_open = {
                            "action": mt.TRADE_ACTION_DEAL,
                            "symbol": SYMBOL,
                            "volume": LOT_SIZE,
                            "type": order_type,
                            "price": current_price,
                            "sl": 0.0,
                            "tp": 0.0,
                            "magic": 2026,
                            "comment": comment,
                            "type_time": mt.ORDER_TIME_GTC,
                            "type_filling": mt.ORDER_FILLING_IOC,
                        }
                        res_open = mt.order_send(request_open)
                        if res_open is None:
                            print(f"❌ Erreur MT5 pour l'ouverture de {comment}")
                        elif res_open.retcode != mt.TRADE_RETCODE_DONE:
                            print(f"❌ Ouverture {comment} REFUSÉE. Code: {res_open.retcode} ({res_open.comment})")
                        else:
                            bot_state["tickets"].append(res_open.order)

                    # --- APPLICATION DES SL/TP PROVISOIRES ---
                    prov_sl_dist = PROV_SL_PIPS * PIP_SIZE
                    prov_tp1_dist = PROV_TP1_PIPS * PIP_SIZE
                    prov_tp2_dist = PROV_TP2_PIPS * PIP_SIZE
                    if order_type == mt.ORDER_TYPE_BUY:
                        prov_sl  = round(current_price - prov_sl_dist, 2)
                        prov_tp1 = round(current_price + prov_tp1_dist, 2)
                        prov_tp2 = round(current_price + prov_tp2_dist, 2)
                    else:  # SELL
                        prov_sl  = round(current_price + prov_sl_dist, 2)
                        prov_tp1 = round(current_price - prov_tp1_dist, 2)
                        prov_tp2 = round(current_price - prov_tp2_dist, 2)

                    bot_state["prov_tp1"] = prov_tp1

                    print(f"🔒 [ETAPE 2] Application SL provisoire={prov_sl} / TP1 provisoire={prov_tp1} / TP2 provisoire={prov_tp2} sur toutes les positions...")
                    for i, ticket in enumerate(bot_state["tickets"]):
                        # TP provisoires : TP1 sur pos 0, TP2 sur pos 1, 0 sur pos 2 (TP3)
                        if i == 0:
                            prov_tp = prov_tp1
                        elif i == 1:
                            prov_tp = prov_tp2
                        else:
                            prov_tp = 0.0
                        req_prov = {
                            "action": mt.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": SYMBOL,
                            "sl": prov_sl,
                            "tp": prov_tp
                        }
                        res_prov = mt.order_send(req_prov)
                        comment_p = f"TP{i+1}"
                        if res_prov is None or res_prov.retcode != mt.TRADE_RETCODE_DONE:
                            code_err = res_prov.retcode if res_prov else "Délai dépassé"
                            print(f"⚠️ {comment_p}: ÉCHEC SL/TP provisoire (Code {code_err})")
                        else:
                            print(f"✅ {comment_p}: SL/TP provisoire appliqués.")

                    # --- ACTIVATION BE IMMÉDIATE (Trigger sur TP1 provisoire) ---
                    active_trades[prov_tp1] = {
                        "ids": bot_state["tickets"],
                        "entry": entry_signal,
                        "type": order_type
                    }

                    bot_state["step"] = 2
                    print(f"👀 [ETAPE 2] {len(bot_state['tickets'])} positions ouvertes avec protection provisoire (BE prévu sur TP1 à {prov_tp1}). Attente des TPs définitifs (Msg 3)...")
                return
                
            elif bot_state["step"] == 2:
                # Message 3 contenant TP1, TP2, SL
                tp1_match = re.search(r'TP1\s*[:\-]?\s*([\d\.]+)', msg)
                tp2_match = re.search(r'TP2\s*[:\-]?\s*([\d\.]+)', msg)
                sl_match = re.search(r'SL\s*[:\-]?\s*([\d\.]+)', msg)
                
                if not (tp1_match and tp2_match and sl_match):
                    return # Ignore si format non reconnu pour l'étape 3
                    
                # Le prix de rappel de ce message ou à défaut Msg 2
                prix_rappel = re.search(r'\b\d{4}(?:\.\d+)?\b', msg)
                entry_signal = float(prix_rappel.group(0)) if prix_rappel else bot_state["entry_price"]
                
                tp1 = float(tp1_match.group(1))
                tp2 = float(tp2_match.group(1))
                sl = float(sl_match.group(1))
                order_type = bot_state["type"]
                
                print(f"🎯 [ETAPE 3] Application SL={sl} et TPs...")
                
                targets_prices = [tp1, tp2, 0.0]
                
                if "tickets" in bot_state:
                    for i, ticket in enumerate(bot_state["tickets"]):
                        if i < len(targets_prices):
                            tp_price = targets_prices[i]
                            if sl > 0 or tp_price > 0:
                                req_mod = {
                                    "action": mt.TRADE_ACTION_SLTP,
                                    "position": ticket,
                                    "symbol": SYMBOL,
                                    "sl": sl,
                                    "tp": tp_price
                                }
                                res_mod = mt.order_send(req_mod)
                                comment = f"TP{i+1}"
                                if res_mod is None or res_mod.retcode != mt.TRADE_RETCODE_DONE:
                                    code_err = res_mod.retcode if res_mod else "Délai dépassé"
                                    detail = res_mod.comment if res_mod else ""
                                    print(f"⚠️ {comment}: ÉCHEC d'ajout SL/TP (Code {code_err}: {detail})")
                                else:
                                    print(f"✅ {comment}: SL/TP appliqués.")
                
                # Mise à jour du Break Even (Trigger sur nouveau TP1)
                if "tickets" in bot_state and bot_state["tickets"]:
                    # Nettoyage de l'ancien TP provisoire s'il existait encore
                    old_tp1 = bot_state.get("prov_tp1")
                    if old_tp1 in active_trades:
                        del active_trades[old_tp1]
                        print(f"🔄 Mise à jour du trigger BE : {old_tp1} -> {tp1}")
                    
                    active_trades[tp1] = {
                        "ids": bot_state["tickets"], 
                        "entry": entry_signal,
                        "type": order_type
                    }
                    print(f"✅ 3 positions finalisées ! SL Break Even prévu à {entry_signal} lors du TP1 ({tp1}).")
                
                bot_state["step"] = 0
                bot_state["tickets"] = []

        except Exception as e:
            print(f"❌ Erreur de la machine à états : {e}")

    # --- TÂCHE DE FOND : SURVEILLANCE BREAK EVEN ---
    async def monitor_be():
        while True:
            if active_trades:
                tick = mt.symbol_info_tick(SYMBOL)
                if tick:
                    # On parcourt une copie de la liste pour pouvoir supprimer des éléments
                    for tp1_p, data in list(active_trades.items()):
                        # Vérification dynamique (BUY ou SELL)
                        tp_hit = False
                        if data["type"] == mt.ORDER_TYPE_BUY and tick.bid >= tp1_p:
                            tp_hit = True
                        elif data["type"] == mt.ORDER_TYPE_SELL and tick.ask <= tp1_p:
                            tp_hit = True
                        
                        if tp_hit:
                            print(f"🛡️ TP1 atteint ({tp1_p}). Sécurisation au Break Even ({data['entry']}).")
                            move_to_be(data["ids"], data["entry"])
                            del active_trades[tp1_p]
            await asyncio.sleep(1) # Vérification toutes les secondes

    asyncio.create_task(monitor_be())
    await client.start()
    print("🤖 Bot 100% Opérationnel. En attente de signaux sur Telegram...")
    await client.run_until_disconnected()

# ==========================================
# 4. FONCTIONS UTILES (BE & CLÔTURE)
# ==========================================
def move_to_be(ids, entry):
    positions = mt.positions_get(symbol=SYMBOL)
    if positions:
        for pos in positions:
            if pos.ticket in ids:
                mt.order_send({
                    "action": mt.TRADE_ACTION_SLTP, 
                    "position": pos.ticket, 
                    "sl": entry, 
                    "tp": pos.tp
                })

def close_position(pos):
    tick = mt.symbol_info_tick(SYMBOL)
    mt.order_send({
        "action": mt.TRADE_ACTION_DEAL, 
        "position": pos.ticket, 
        "symbol": SYMBOL, 
        "volume": pos.volume,
        "type": mt.ORDER_TYPE_SELL if pos.type == mt.ORDER_TYPE_BUY else mt.ORDER_TYPE_BUY,
        "price": tick.bid if pos.type == mt.ORDER_TYPE_BUY else tick.ask,
        "magic": 2026, 
        "type_filling": mt.ORDER_FILLING_IOC
    })

if __name__ == "__main__":
    asyncio.run(start_bot())
