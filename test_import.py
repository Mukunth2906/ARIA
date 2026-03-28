"""Quick import test for the backend."""
import traceback
import sys

log = open("test_result.txt", "w", encoding="utf-8")

def p(msg):
    print(msg)
    log.write(msg + "\n")
    log.flush()

try:
    p("Step 1: Importing backend.state...")
    from backend.state import AgentState
    p("  OK")
    
    p("Step 2: Importing backend.utils.llm...")
    from backend.utils.llm import get_llm
    p("  OK")
    
    p("Step 3: Importing backend.profile.schema...")
    from backend.profile.schema import UserProfile
    p("  OK")
    
    p("Step 4: Importing backend.utils.db...")
    from backend.utils.db import load_profile
    p("  OK")
    
    p("Step 5: Importing backend.graph...")
    from backend.graph import build_graph
    p("  OK")
    
    p("Step 6: Importing backend.main...")
    from backend.main import app
    p("  OK")
    
    p("\n=== ALL IMPORTS SUCCESSFUL ===")
except Exception as e:
    p(f"\n=== IMPORT FAILED ===")
    log.write(traceback.format_exc())
    traceback.print_exc()

log.close()
