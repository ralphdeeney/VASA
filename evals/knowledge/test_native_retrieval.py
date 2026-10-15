"""Declared acceptance: top-1 accuracy >= 0.90 over independent paraphrase queries.

Native CPU MiniLM inference; missing artifacts are an actionable failure.
"""

import time

import numpy as np
import pytest

from vasa.knowledge.embedding import CPUEmbedder

CORPUS = [
    "Our clinic operates Monday through Friday from 9am until 5pm. It is closed weekends.",
    "Appointments must be cancelled at least 24 hours in advance to avoid a cancellation fee.",
    "We accept Visa and Mastercard credit cards, bank transfers, and cash payments.",
    "Our shop is located at 18 Oak Avenue, opposite the central railway station.",
    "Unopened products can be returned within 30 days with the original receipt for a refund.",
    "Standard delivery takes three to five business days. Express shipping arrives the next day.",
    "A dental cleaning costs sixty dollars. The initial consultation is free of charge.",
    "Customers can book appointments online or by calling our reception desk.",
    "The hotel permits small dogs in designated rooms for an additional nightly charge.",
    "All repairs are covered by a twelve month warranty against faulty workmanship.",
]
QUERIES = [
    ("Are you open on Saturday?", 0),
    ("How much notice do I need to give if I cannot attend my appointment?", 1),
    ("Can I pay with a credit card?", 2),
    ("What is your address?", 3),
    ("What is the refund policy if I have not opened the item?", 4),
    ("How long will my parcel take to arrive?", 5),
    ("What is the price for getting my teeth cleaned?", 6),
    ("How do I reserve a time to visit?", 7),
    ("Can I bring my puppy when I stay overnight?", 8),
    ("How long is the guarantee on your repair work?", 9),
    ("Which days can I visit the clinic?", 0),
    ("Is there a penalty for cancelling at the last minute?", 1),
    ("Do you take bank transfers?", 2),
    ("Are you near the train station?", 3),
    ("Must I keep my receipt to return a purchase?", 4),
    ("Is overnight shipping available?", 5),
    ("Do I have to pay for the first consultation?", 6),
    ("Can reception help me schedule an appointment?", 7),
    ("Is your accommodation pet friendly?", 8),
    ("Is defective workmanship covered for a year?", 9),
]


@pytest.mark.eval
def test_native_semantic_retrieval() -> None:
    started = time.monotonic()
    embedder = CPUEmbedder()
    vectors = np.asarray(embedder.embed(CORPUS + [query for query, _ in QUERIES]))
    assert vectors.shape == (30, 384)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    predictions = np.argmax(vectors[10:] @ vectors[:10].T, axis=1)
    accuracy = sum(
        int(prediction == expected)
        for prediction, (_, expected) in zip(predictions, QUERIES, strict=True)
    ) / len(QUERIES)
    print(
        f"native_retrieval_top1={accuracy:.3f} queries=20 elapsed={time.monotonic() - started:.3f}s"
    )
    assert accuracy >= 0.90
