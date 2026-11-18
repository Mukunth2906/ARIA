"""
tests/eval_rag.py — Persistent RAG Retrieval Quality, Metadata Filtering & Privacy Evaluation

Evaluates ARIA's persistent ChromaDB RAG layer across 6 dimensions:
  1. Disk Persistence (re-opening PersistentClient across restart)
  2. Retrieval Quality Benchmark (Hit@1, Hit@3, MRR on paraphrased ambiguous queries)
  3. Metadata Filtering (doc_type, recipient_email, timestamp / max_age_days)
  4. Multi-User Isolation (zero cross-tenant leakage)
  5. Privacy, Consent, PII Rejection, Retention TTL Purging & Right-to-be-Forgotten Deletion
  6. Source Attribution Completeness (doc_id, source_label, timestamp_iso, similarity)

Run:
  python tests/eval_rag.py
"""
import os
import shutil
import sys
import tempfile
import time

# Ensure project root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.utils.vector_store import (
    upsert_context,
    query_context,
    list_user_context,
    delete_context_item,
    delete_all_user_context,
    purge_expired_context,
    reset_client_cache,
)


def run_evaluation():
    tmp_dir = tempfile.mkdtemp(prefix="aria_rag_eval_")
    print(f"=== ARIA Persistent RAG Evaluation ===")
    print(f"Isolated ChromaDB persist_dir: {tmp_dir}\n")

    now = int(time.time())
    day = 86400

    try:
        # ── 1. Seed Realistic Multi-Type Corpus for User 'alice' ─────────────
        corpus = [
            {
                "doc_id": "doc_q3_finance",
                "doc_type": "sent_email",
                "source_label": "Sent email to Priya Sharma — Q3 Revenue Breakdown",
                "recipient_email": "priya@corp.com",
                "subject": "Q3 Revenue Breakdown",
                "timestamp": now - (2 * day),
                "text": (
                    "Sent formal email to Priya Sharma <priya@corp.com> (engineering manager). "
                    "Subject: Q3 Revenue Breakdown. Summary: Shared the quarterly financial spreadsheet "
                    "and budget forecast for Q3 fiscal review."
                ),
            },
            {
                "doc_id": "doc_azure_contact",
                "doc_type": "contact_note",
                "source_label": "Contact note — Dev Nair (Cloud Infrastructure)",
                "recipient_email": "dev.nair@corp.com",
                "subject": "Cloud Infrastructure Contact",
                "timestamp": now - (3 * day),
                "text": (
                    "Dev Nair <dev.nair@corp.com> manages Azure cloud credits, Kubernetes cluster "
                    "quotas, and monthly cloud billing invoices for the platform team."
                ),
            },
            {
                "doc_id": "doc_dentist_cal",
                "doc_type": "calendar_event",
                "source_label": "Calendar event: Dental Checkup with Dr. Meera",
                "recipient_email": "clinic@smilecare.in",
                "subject": "Dental Checkup",
                "timestamp": now - (1 * day),
                "text": (
                    "Scheduled calendar event 'Annual Dental Checkup' with Dr. Meera at SmileCare "
                    "Clinic on Thursday at 11:00 AM. Reminder set 10 minutes prior."
                ),
            },
            {
                "doc_id": "doc_sprint_cal",
                "doc_type": "calendar_event",
                "source_label": "Calendar event: Backend Sprint Retrospective",
                "recipient_email": "raj@corp.com",
                "subject": "Sprint Retrospective",
                "timestamp": now - (2 * day),
                "text": (
                    "Scheduled calendar event 'Backend Sprint Retrospective' with Raj Patel "
                    "<raj@corp.com> on Friday at 4:00 PM to review API latency metrics and bug backlog."
                ),
            },
            {
                "doc_id": "doc_vendor_old",
                "doc_type": "sent_email",
                "source_label": "Sent email to Vendor — Legacy Hardware Quote",
                "recipient_email": "sales@hardwarehub.com",
                "subject": "Monitor Stand Quote",
                "timestamp": now - (45 * day),
                "text": (
                    "Sent email to HardwareHub sales <sales@hardwarehub.com> requesting a quote "
                    "for 10 ergonomic aluminum monitor stands for the Chennai office."
                ),
            },
            {
                "doc_id": "doc_travel_summary",
                "doc_type": "session_summary",
                "source_label": "Session summary — Bengaluru Flight Booking",
                "recipient_email": "travel@corp.com",
                "subject": "Bengaluru Trip",
                "timestamp": now - (4 * day),
                "text": (
                    "Booked Indigo morning flight from Chennai (MAA) to Bengaluru (BLR) for the "
                    "AI Summit conference; prefers window seat and vegetarian meal."
                ),
            },
        ]

        for item in corpus:
            res = upsert_context(
                user_id="alice",
                doc_id=item["doc_id"],
                text=item["text"],
                doc_type=item["doc_type"],
                source_label=item["source_label"],
                recipient_email=item["recipient_email"],
                subject=item["subject"],
                timestamp=item["timestamp"],
                retention_days=90,
                consent=True,
                pii_clean=True,
                persist_dir=tmp_dir,
            )
            assert res["indexed"], f"Failed to index {item['doc_id']}: {res}"

        # Seed a private doc for another user 'bob' (isolation test)
        bob_res = upsert_context(
            user_id="bob",
            doc_id="doc_bob_secret",
            text="Project Apollo launch readiness checklist and private acquisition timeline for Bob.",
            doc_type="sent_email",
            source_label="Bob's confidential email — Project Apollo",
            recipient_email="ceo@othercorp.com",
            subject="Project Apollo",
            timestamp=now - day,
            persist_dir=tmp_dir,
        )
        assert bob_res["indexed"]

        # Seed an already-expired doc for 'alice' (retention TTL test)
        exp_res = upsert_context(
            user_id="alice",
            doc_id="doc_expired_note",
            text="Temporary parking pass code for basement level B2 last summer.",
            doc_type="session_summary",
            source_label="Expired parking note",
            timestamp=now - (120 * day),
            retention_days=30,  # expired 90 days ago
            persist_dir=tmp_dir,
        )
        assert exp_res["indexed"]

        # ── 2. Disk Persistence Check (Simulate Server Restart) ──────────────
        reset_client_cache(tmp_dir)
        reloaded = list_user_context("alice", persist_dir=tmp_dir)
        assert len(reloaded) == len(corpus) + 1, f"Expected {len(corpus) + 1} persisted docs, got {len(reloaded)}"
        print(f"[PASS] 1. Disk Persistence: {len(reloaded)} docs survived PersistentClient reload.")

        # ── 3. Retrieval Quality Benchmark (Paraphrased Ambiguous Queries) ───
        eval_queries = [
            ("Send that quarterly budget spreadsheet to my manager", "doc_q3_finance"),
            ("Who do I email about Azure cloud billing and Kubernetes quotas?", "doc_azure_contact"),
            ("When is my teeth appointment with Dr. Meera?", "doc_dentist_cal"),
            ("Reschedule Friday's API latency review meeting with Raj", "doc_sprint_cal"),
            ("Follow up on the ergonomic monitor stand order for Chennai", "doc_vendor_old"),
            ("What airline and meal preference did I pick for the Bengaluru AI conference?", "doc_travel_summary"),
        ]

        hit_at_1 = 0
        hit_at_3 = 0
        reciprocal_ranks = []

        print("\n--- 2. Retrieval Quality Benchmark ---")
        for q_text, expected_id in eval_queries:
            hits = query_context("alice", q_text, n_results=3, persist_dir=tmp_dir)
            returned_ids = [h["doc_id"] for h in hits]
            top1 = returned_ids[0] if returned_ids else None
            rank = (returned_ids.index(expected_id) + 1) if expected_id in returned_ids else None

            if rank == 1:
                hit_at_1 += 1
            if rank is not None and rank <= 3:
                hit_at_3 += 1
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)

            top_sim = hits[0]["similarity"] if hits else 0.0
            status = "HIT@1" if rank == 1 else (f"HIT@{rank}" if rank else "MISS")
            print(f"  [{status:5}] sim={top_sim:.2f} | expected={expected_id} | got={top1} | query='{q_text[:48]}...'")

            # Verify source attribution fields on every returned hit
            for h in hits:
                assert h.get("doc_id") and h.get("source_label") and h.get("timestamp_iso")
                assert 0.0 <= h.get("similarity", -1) <= 1.0

        n = len(eval_queries)
        p1 = hit_at_1 / n
        r3 = hit_at_3 / n
        mrr = sum(reciprocal_ranks) / n
        print(f"\n  Metrics => Hit@1: {p1:.0%} ({hit_at_1}/{n}) | Hit@3: {r3:.0%} ({hit_at_3}/{n}) | MRR: {mrr:.3f}")
        assert p1 >= 0.80, f"Hit@1 below threshold: {p1}"
        assert r3 == 1.0, f"Hit@3 below 100%: {r3}"
        print("[PASS] 2. Retrieval Quality & Source Attribution passed benchmark thresholds.")

        # ── 4. Metadata Filtering Tests ──────────────────────────────────────
        # 4a. Filter by doc_type
        cal_hits = query_context(
            "alice",
            "meeting appointment schedule review",
            n_results=5,
            doc_types=["calendar_event"],
            persist_dir=tmp_dir,
        )
        assert len(cal_hits) >= 1 and all(h["doc_type"] == "calendar_event" for h in cal_hits)

        # 4b. Filter by recipient_email
        priya_hits = query_context(
            "alice",
            "financial report",
            n_results=5,
            recipient_email="priya@corp.com",
            persist_dir=tmp_dir,
        )
        assert len(priya_hits) == 1 and priya_hits[0]["doc_id"] == "doc_q3_finance"

        # 4c. Filter by recency (max_age_days=7 should exclude 45-day-old doc_vendor_old)
        recent_hits = query_context(
            "alice",
            "monitor stand quote Chennai",
            n_results=5,
            max_age_days=7,
            persist_dir=tmp_dir,
        )
        assert all(h["doc_id"] != "doc_vendor_old" for h in recent_hits)
        print("[PASS] 3. Metadata Filtering (doc_type, recipient_email, timestamp/recency) verified.")

        # ── 5. Multi-User Isolation Test ─────────────────────────────────────
        leak_hits = query_context(
            "alice",
            "Project Apollo launch readiness checklist acquisition",
            n_results=3,
            persist_dir=tmp_dir,
        )
        assert all(h["doc_id"] != "doc_bob_secret" for h in leak_hits)
        print("[PASS] 4. Multi-User Isolation: 0 cross-user records leaked from 'bob' to 'alice'.")

        # ── 6. Privacy, Consent, PII Gate, Retention & Deletion Tests ────────
        # 6a. Consent = False rejected
        no_consent = upsert_context(
            user_id="alice",
            text="Private note that must not be indexed",
            doc_type="session_summary",
            source_label="No consent test",
            consent=False,
            persist_dir=tmp_dir,
        )
        assert not no_consent["indexed"]

        # 6b. Upstream pii_clean = False rejected
        pii_flagged = upsert_context(
            user_id="alice",
            text="Normal text flagged by upstream scanner",
            doc_type="sent_email",
            source_label="PII flagged test",
            pii_clean=False,
            persist_dir=tmp_dir,
        )
        assert not pii_flagged["indexed"]

        # 6c. Deterministic local secret scanner blocks API keys & passwords even if pii_clean=True
        secret_doc = upsert_context(
            user_id="alice",
            text="Here is the prod key sk-1234567890abcdef1234567890 and password=SuperSecret99",
            doc_type="sent_email",
            source_label="Secret leak test",
            pii_clean=True,
            persist_dir=tmp_dir,
        )
        assert not secret_doc["indexed"], "Secret scanner failed to block API key/password!"

        # 6d. Expired doc is excluded at query time and removed by purge_expired_context
        exp_query = query_context("alice", "parking pass basement B2", n_results=3, exclude_expired=True, persist_dir=tmp_dir)
        assert all(h["doc_id"] != "doc_expired_note" for h in exp_query)
        purged = purge_expired_context("alice", persist_dir=tmp_dir)
        assert purged == 1, f"Expected 1 expired doc purged, got {purged}"

        # 6e. Single-item deletion
        assert delete_context_item("alice", "doc_vendor_old", persist_dir=tmp_dir) is True
        after_del = query_context("alice", "ergonomic monitor stand quote", n_results=3, persist_dir=tmp_dir)
        assert all(h["doc_id"] != "doc_vendor_old" for h in after_del)

        # 6f. Right-to-be-Forgotten full user wipe
        wiped = delete_all_user_context("alice", persist_dir=tmp_dir)
        assert wiped == len(corpus) - 1
        assert len(list_user_context("alice", persist_dir=tmp_dir)) == 0
        # Ensure bob's collection is untouched after alice's wipe
        assert len(list_user_context("bob", persist_dir=tmp_dir)) == 1
        print("[PASS] 5. Privacy, Consent, PII Blocking, Retention Purge & Right-to-be-Forgotten verified.")

        print("\n=== ALL PERSISTENT RAG EVALUATIONS PASSED ===")
    finally:
        reset_client_cache(tmp_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_evaluation()

