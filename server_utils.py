# server_utils.py

import os
import subprocess
from datetime import datetime
from io import TextIOWrapper
from typing import Dict

# Constants
SERVER_PATH = "./server/xRC Simulator.x86_64"
SERVER_LOGS_DIR = "./server_logs/"
PORTS = [11115, 11116, 11117, 11118, 11119, 11120]

servers_active: Dict[int, subprocess.Popen] = {}
log_files: Dict[int, TextIOWrapper] = {}
last_active: Dict[int, datetime] = {}

# Function to start a server process
def start_server_process(game: str, comment: str, password: str = "", admin: str = "Admin",
                         restart_mode: int = -1, frame_rate: int = 120, update_time: int = 10,
                         tournament_mode: bool = True, start_when_ready: bool = True,
                         register: bool = True, spectators: int = 4, min_players: int = -1,
                         restart_all: bool = True):
    if not os.path.exists(SERVER_PATH):
        return "⚠ xRC Sim server not found, use `/update` to update", -1

    if len(servers_active) >= len(PORTS):
        return "⚠ The maximum number of servers are already running", -1

    port = -1
    for p in PORTS:
        if p not in servers_active:
            port = p
            break

    if port == -1:
        return "⚠ Could not find a port to run the server on", -1

    # Game settings and default values would be fetched or set here
    game_settings = ""
    if restart_mode == -1:
        restart_mode = 1
    if min_players == -1:
        min_players = 4

    # Open log file in append mode
    f = open(f"{SERVER_LOGS_DIR}{port}.log", "a")
    log_files[port] = f
    f.write(f"Server started at {datetime.now()}")

    command = [
        SERVER_PATH, "-batchmode", "-nographics",
        f"RouterPort={port}", f"Port={port}", f"Game={game}",
        f"GameOption={restart_mode}", f"FrameRate={frame_rate}",
        f"Tmode={'On' if tournament_mode else 'Off'}",
        f"Register={'On' if register else 'Off'}",
        f"Spectators={spectators}", f"UpdateTime={update_time}",
        "MaxData=1000000",
        f"StartWhenReady={'On' if start_when_ready else 'Off'}",
        f"Comment={comment}", f"Password={password}",
        f"Admin={admin}", f"GameSettings={game_settings}",
        f"MinPlayers={min_players}",
        f"RestartAll={'On' if restart_all else 'Off'}",
        "NetStats=On", "Profiling=On"
    ]

    servers_active[port] = subprocess.Popen(
        command,
        stdout=f, stderr=f, shell=False
    )

    last_active[port] = datetime.now()

    return f"✅ Launched server '{comment}' on port {port}", port

# Function to stop a server process
def stop_server_process(port: int):
    if port not in servers_active:
        return f"⚠ Server on port {port} not found"

    log_files[port].write(f"Server shut down at {datetime.now()}")

    servers_active[port].terminate()
    log_files[port].close()
    del servers_active[port]
    del last_active[port]
    del log_files[port]

    return f"✅ Server on port {port} shut down"
