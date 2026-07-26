import sys
import os
import time
import json
from typing import List, Dict

# Add backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session, create_engine, select
from sqlalchemy import text
from models import LearningExample
from config import settings
from services.embedder import TextEmbedder
from services.classifier import TicketClassifier
from services.llm_client import predict_fault_and_severity

# Disable MOCK_LLM so we actually hit the LLM for the pure LLM benchmark
# (Or if the user is in MOCK mode, it will just test the mock time vs history time, which is fine)

def populate_mock_history(session: Session, embedder: TextEmbedder):
    """Insert some mock learning examples to simulate past resolved tickets."""
    # Check if we already have some
    if session.query(LearningExample).count() > 0:
        return
    
    mock_data = [
        ("my password is locked", "login/access", "normal"),
        ("the entire payroll system is down for everyone", "total outage", "critical"),
        ("system is very slow today", "performance/slow", "normal"),
        ("meri salary mismatch hai", "data error", "normal"),
        ("leave portal submit button not working", "partial/degraded", "normal"),
    ]
    
    print("Populating mock history examples...")
    for text_val, f_type, sev in mock_data:
        emb = embedder.get_embedding(text_val)
        example = LearningExample(
            intake_id=None,
            ticket_number="MOCK123",
            raw_transcript=text_val,
            text_embedding=emb,
            confirmed_fault_type=f_type,
            confirmed_severity=sev,
            confirmed_app_id=None,
        )
        session.add(example)
    session.commit()
    print("Mock history populated.")

def run_evaluation():
    engine = create_engine(settings.DATABASE_URL)
    session = Session(engine)
    embedder = TextEmbedder()
    classifier = TicketClassifier()
    
    populate_mock_history(session, embedder)
    
    test_set = [
        # Near matches to history
        "my password is locked and I cannot get in",
        "the payroll system is completely down for all users",
        "system is extremely slow right now",
        "meri salary mismatch aa rahi hai",
        "submit button on leave portal is broken",
        
        # Novel complaints
        "I cannot access my email",
        "the printer on the 3rd floor is jammed",
        "vpn connection drops every 5 minutes",
        "need a new mouse",
        "how do I install python?",
        
        # More variations
        "forgot my password",
        "account locked out after 3 tries",
        "application hanging indefinitely",
        "data on the dashboard is wrong",
        "part of the website is not loading",
        "everyone in my unit cannot access the server",
        "minor typo on the homepage",
        "screen is flickering",
        "urgent: mission critical system offline",
        "unable to download the report",
        
        "login page giving 500 error",
        "slow performance on database queries",
        "incorrect figures in the financial summary",
        "sab ke liye network down hai",
        "UI color is wrong on the submit button",
        "server unreachable",
        "I need access to the shared drive",
        "team is unable to upload files",
        "cosmetic issue on the footer",
        "can't log in to the portal",
    ]
    
    results = []
    
    history_matches = 0
    history_correct = 0
    history_incorrect = 0
    
    total_hybrid_time = 0
    total_pure_llm_time = 0
    
    print(f"Starting evaluation on {len(test_set)} complaints...")
    print("-" * 50)
    
    for text_val in test_set:
        # 1. Prepare embedding
        emb = embedder.get_embedding(text_val)
        
        # 2. Pure LLM classification
        t0 = time.time()
        pure_llm_res = predict_fault_and_severity(text_val)
        pure_llm_fault = pure_llm_res.get("fault_type", "other")
        pure_llm_severity = pure_llm_res.get("severity", "normal")
        t_pure_llm = (time.time() - t0) * 1000
        
        # 3. Hybrid classification (History + LLM fallback)
        t0 = time.time()
        hybrid_fault, hybrid_severity = classifier.classify_complaint(session, text_val, emb)
        t_hybrid = (time.time() - t0) * 1000
        
        # Was history used?
        # We can check if it was a history match by calling _get_history_match_combined directly
        t0_hist = time.time()
        hist_f, hist_s = classifier._get_history_match_combined(session, emb)
        t_hist_only = (time.time() - t0_hist) * 1000
        
        used_history = (hist_f is not None and hist_s is not None)
        
        total_hybrid_time += t_hybrid
        total_pure_llm_time += t_pure_llm
        
        if used_history:
            history_matches += 1
            # Check accuracy vs pure LLM
            if hybrid_fault == pure_llm_fault and hybrid_severity == pure_llm_severity:
                history_correct += 1
            else:
                history_incorrect += 1
                
        results.append({
            "text": text_val,
            "used_history": used_history,
            "hybrid_result": f"{hybrid_fault}/{hybrid_severity}",
            "pure_llm_result": f"{pure_llm_fault}/{pure_llm_severity}",
            "hybrid_time_ms": t_hybrid,
            "pure_llm_time_ms": t_pure_llm,
        })
    
    # Generate report
    print("\n" + "="*50)
    print("CLASSIFICATION HISTORY EVALUATION REPORT")
    print("="*50)
    
    print(f"Total Complaints Tested : {len(test_set)}")
    
    pct_history = (history_matches / len(test_set)) * 100
    print(f"Classified via History  : {history_matches} ({pct_history:.1f}%)")
    
    if history_matches > 0:
        pct_correct = (history_correct / history_matches) * 100
        print(f"History Accuracy (vs LLM): {pct_correct:.1f}%")
        if history_incorrect > 0:
            print(f"History Mismatches      : {history_incorrect}")
            for r in results:
                if r["used_history"] and r["hybrid_result"] != r["pure_llm_result"]:
                    print(f"  - '{r['text']}'")
                    print(f"    History gave: {r['hybrid_result']}")
                    print(f"    LLM gave    : {r['pure_llm_result']}")
                    
    avg_hybrid = total_hybrid_time / len(test_set)
    avg_pure_llm = total_pure_llm_time / len(test_set)
    savings = avg_pure_llm - avg_hybrid
    
    print("\nLATENCY COMPARISON (Average per complaint):")
    print(f"Pure LLM approach       : {avg_pure_llm:.1f} ms")
    print(f"Hybrid (History+LLM)    : {avg_hybrid:.1f} ms")
    print(f"Average Savings         : {savings:.1f} ms")
    
    print("\n" + "="*50)
    
    # Save results to a file for artifact use
    with open("eval_results.json", "w") as f:
        json.dump({
            "total": len(test_set),
            "history_matches": history_matches,
            "history_correct": history_correct,
            "avg_hybrid_time": avg_hybrid,
            "avg_pure_llm_time": avg_pure_llm,
            "savings": savings,
            "results": results
        }, f, indent=2)

if __name__ == "__main__":
    run_evaluation()
