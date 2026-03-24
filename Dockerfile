FROM tobix/pywine:3.9

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99

# On ajoute wget pour télécharger MT5
RUN apt-get update && \
    apt-get install -y python3 python3-pip xvfb wget x11vnc && \
    apt-get clean

# 1. On installe les paquets Linux
RUN pip3 install telethon mt5linux rpyc || pip3 install --break-system-packages telethon mt5linux rpyc

# 2. On configure Wine et on installe les libs Python Windows
RUN xvfb-run -a wine reg add "HKEY_CURRENT_USER\Software\Wine\Version" /v "Version" /t REG_SZ /d "win10" /f && \
    xvfb-run -a wine python -m pip install MetaTrader5 rpyc mt5linux

# 3. L'INSTALLATION OFFICIELLE (Celle qui télécharge les bons DLL Windows !)
RUN wget -O mt5setup.exe https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe && \
    (xvfb-run -a wine mt5setup.exe /auto || true) && \
    echo "Installation de MT5 en arrière-plan (60s)..." && \
    sleep 60 && \
    wineserver -k || true && \
    rm mt5setup.exe

WORKDIR /app
COPY bot.py .

# 5. Démarrage avec Serveur Visuel (VNC)
CMD bash -c "Xvfb :99 -screen 0 1024x768x24 & export DISPLAY=:99 && sleep 2 && x11vnc -display :99 -forever -shared -passwd password123 -listen 0.0.0.0 & sleep 2 && wine 'C:\\Program Files\\MetaTrader 5\\terminal64.exe' /portable & sleep 10 && wine python -m mt5linux & sleep 5 && python3 bot.py"
