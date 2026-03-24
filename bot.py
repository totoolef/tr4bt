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
CHAL_NAME = 't4botcashtest'        # Nom du canal Telegram

# --- STRATÉGIE ---
SYMBOL = "XAUUSD"
LOT_SIZE = 0.02
MAX_DISTANCE = 1.5                # Décalage max toléré (1.0$ sur l'Or)

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
    # Ici, mets ta ligne habituelle pour lancer Telegram (ex: client.run_until_disconnected())
    
    client = TelegramClient('session_docker', API_ID, API_HASH)

    @client.on(events.NewMessage(chats=CHAL_NAME))
    async def handler(event):
        msg = event.raw_text.upper()
        
        # --- CAS 1 : FERMETURE MANUELLE TP3 ---
        if "TP3 MANUEL" in msg:
            positions = mt.positions_get(symbol=SYMBOL)
            if positions:
                for pos in positions:
                    if pos.comment == "TP3":
                        close_position(pos)
                print("✅ Positions TP3 fermées manuellement.")
            return

        # --- CAS 2 : NOUVEAU SIGNAL ---
        try:
            # Extraction des prix
            price_match = re.search(r'(?:BUY|SELL)\s+([\d\.]+)', msg)
            tp1_match = re.search(r'TP1\s+([\d\.]+)', msg)
            tp2_match = re.search(r'TP2\s+([\d\.]+)', msg)
            sl_match = re.search(r'SL\s+([\d\.]+)', msg)

            if not all([price_match, tp1_match, tp2_match, sl_match]): 
                return # Ignore les messages qui n'ont pas le bon format

            entry_signal = float(price_match.group(1))
            tp1 = float(tp1_match.group(1))
            tp2 = float(tp2_match.group(1))
            sl = float(sl_match.group(1))
            order_type = mt.ORDER_TYPE_BUY if "BUY" in msg else mt.ORDER_TYPE_SELL

            # --- VÉRIFICATION DU PRIX (SLIPPAGE) ---
            mt.symbol_select(SYMBOL, True)
        
            # On force MT5 à télécharger les derniers prix
            mt.copy_rates_from_pos(SYMBOL, mt.TIMEFRAME_M1, 0, 1)
        
            tick = mt.symbol_info_tick(SYMBOL)
        
            if tick is None or tick.ask == 0:
                print(f"❌ Erreur : Prix invalide (0.0) pour {SYMBOL}. Tentative de réveil...")
                # Petite pause pour laisser le temps au réseau de charger
                time.sleep(1)
                tick = mt.symbol_info_tick(SYMBOL)
                if tick is None or tick.ask == 0:
                    return

            current_price = tick.ask if order_type == mt.ORDER_TYPE_BUY else tick.bid
            
            if abs(current_price - entry_signal) > MAX_DISTANCE:
                print(f"⚠️ SIGNAL REJETÉ : Prix trop éloigné ({current_price} vs {entry_signal})")
                return

            print(f"🚀 Exécution du signal : {SYMBOL} à {current_price}...")
            
            # --- OUVERTURE DES 3 POSITIONS ---
            targets = [("TP1", tp1), ("TP2", tp2), ("TP3", 0.0)]
            trade_ids = []

            for comment, tp_price in targets:
                request = {
                    "action": mt.TRADE_ACTION_DEAL,
                    "symbol": SYMBOL,
                    "volume": LOT_SIZE,
                    "type": order_type,
                    "price": current_price,
                    "sl": sl,
                    "tp": tp_price,
                    "magic": 2026,
                    "comment": comment,
                    "type_time": mt.ORDER_TIME_GTC,
                    "type_filling": mt.ORDER_FILLING_IOC,
                }
                res = mt.order_send(request)
		# AJOUTE CE BLOC ICI (Diagnostic) :
                if res is None:
                    print(f"❌ Erreur critique : Pas de réponse de MT5 pour l'ordre {comment}")
                elif res.retcode != mt.TRADE_RETCODE_DONE:
                    print(f"❌ Ordre {comment} REFUSÉ. Code erreur : {res.retcode}")
                    print(f"Détail : {res.comment}")
                # FIN DU BLOC DIAGNOSTIC
                if res.retcode == mt.TRADE_RETCODE_DONE:
                    trade_ids.append(res.order)
            
            # Sauvegarde pour le suivi du Break Even
            if trade_ids:
                active_trades[tp1] = {
                    "ids": trade_ids, 
                    "entry": current_price, 
                    "type": order_type
                }
                print(f"✅ 3 positions ouvertes avec succès.")

        except Exception as e:
            print(f"❌ Erreur lors de la lecture du signal : {e}")

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
