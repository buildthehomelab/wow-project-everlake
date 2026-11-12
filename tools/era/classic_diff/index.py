"""Index one TACT build: python3 index.py <work dir>/cache-<name> <product>."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tact"))
import tact
t = tact.Tact(sys.argv[1], product=sys.argv[2])
print(t.version, t.db.execute("SELECT COUNT(*) FROM files").fetchone()[0])
