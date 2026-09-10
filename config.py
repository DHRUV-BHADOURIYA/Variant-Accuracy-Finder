from pathlib import Path

# V1 defaults.
# This is the local Windows path currently used for the Titan/4PC engine.
ENGINE_PATH = Path(r"C:\Users\dell\Desktop\Testing\Current Best\FirstProject.exe")

ANALYSIS_DEPTH = 20
MULTI_PV = 3
ENGINE_THREADS = 1
REPORT_DIRECTORY = Path("reports")

# Exact Chess.com/Fairy-Stockfish 4PC starting position used by the engine.
START_FEN = (
    "R-0,0,0,0-1,1,1,1-1,1,1,1-0,0,0,0-0-x,x,x,yR,yN,yB,yK,yQ,yB,yN,yR,x,x,x/"
    "x,x,x,yP,yP,yP,yP,yP,yP,yP,yP,x,x,x/x,x,x,8,x,x,x/"
    "bR,bP,10,gP,gR/bN,bP,10,gP,gN/bB,bP,10,gP,gB/"
    "bQ,bP,10,gP,gK/bK,bP,10,gP,gQ/bB,bP,10,gP,gB/"
    "bN,bP,10,gP,gN/bR,bP,10,gP,gR/x,x,x,8,x,x,x/"
    "x,x,x,rP,rP,rP,rP,rP,rP,rP,rP,rP,x,x,x/x,x,x,rR,rN,rB,rQ,rK,rB,rN,rR,x,x,x"
)
