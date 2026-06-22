"""
qa_handler.py
─────────────
Stub handler for the UrbanQA question-answering system.

Returns demo responses with confidence scores for the dashboard.
Replace the process_query() logic with a real NLP/RAG pipeline later.
"""

from __future__ import annotations

import logging
import random

log = logging.getLogger(__name__)


_DEMO_QA = {
    "munich": {
        "answer": "Munich (München) is the capital and largest city of "
                  "Bavaria, Germany. It is known for its annual Oktoberfest "
                  "celebration, historic architecture, and role as a major "
                  "center for science, technology, and the automotive industry.",
        "confidence": 0.92,
        "source": "munich_wiki_p1",
    },
    "population": {
        "answer": "Munich has a population of approximately 1.5 million "
                  "people within the city limits, making it the third-largest "
                  "city in Germany after Berlin and Hamburg.",
        "confidence": 0.88,
        "source": "munich_wiki_p3",
    },
    "districts": {
        "answer": "Munich is divided into 25 boroughs (Stadtbezirke). "
                  "Notable districts include Altstadt-Lehel (the historic "
                  "center), Schwabing, Maxvorstadt, and Bogenhausen.",
        "confidence": 0.85,
        "source": "munich_wiki_p12",
    },
    "transportation": {
        "answer": "Munich has an extensive public transportation network "
                  "including the U-Bahn (subway), S-Bahn (suburban rail), "
                  "trams, and buses operated by MVV. The city also has a "
                  "major international airport (MUC).",
        "confidence": 0.90,
        "source": "munich_transport_p1",
    },
    "oktoberfest": {
        "answer": "Oktoberfest is the world's largest folk festival, held "
                  "annually in Munich on the Theresienwiese fairgrounds. "
                  "It typically runs from late September to the first "
                  "weekend in October, attracting over 6 million visitors.",
        "confidence": 0.94,
        "source": "munich_wiki_p42",
    },
    "traffic": {
        "answer": "Munich's traffic network includes major highways (A9, A92, "
                  "A96, A99) forming a ring around the city. The Mittlerer Ring "
                  "is the main inner-city bypass. Traffic congestion is common "
                  "during rush hours, particularly on the A99 and approaches "
                  "to the city center.",
        "confidence": 0.87,
        "source": "munich_traffic_p5",
    },
    "landmarks": {
        "answer": "Key landmarks include the Marienplatz with its New Town Hall "
                  "and Glockenspiel, Frauenkirche (Cathedral), Nymphenburg Palace, "
                  "Englischer Garten (one of the world's largest urban parks), "
                  "BMW Welt, and the Deutsches Museum.",
        "confidence": 0.91,
        "source": "munich_wiki_p8",
    },
}

_KEYWORD_MAP = {
    "munich": ["munich", "münchen", "city", "known for", "about"],
    "population": ["population", "people", "inhabitants", "how many"],
    "districts": ["district", "borough", "neighborhood", "area"],
    "transportation": ["transport", "train", "bus", "subway", "u-bahn", "s-bahn", "airport"],
    "oktoberfest": ["oktoberfest", "festival", "beer"],
    "traffic": ["traffic", "road", "highway", "congestion", "driving"],
    "landmarks": ["landmark", "monument", "attraction", "visit", "see", "building"],
}


class UrbanQAHandler:
    def __init__(self):
        log.info("UrbanQA handler initialized (demo/stub mode)")

    def process_query(self, query: str) -> dict:
        if not query or not query.strip():
            return {
                "answer": "Please enter a question.",
                "confidence": 0.0,
                "source": "",
            }

        query_lower = query.lower()

        best_match = None
        best_score = 0

        for topic, keywords in _KEYWORD_MAP.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > best_score:
                best_score = score
                best_match = topic

        if best_match and best_score > 0:
            result = _DEMO_QA[best_match].copy()
            result["confidence"] = min(1.0, max(0.0,
                result["confidence"] + random.uniform(-0.05, 0.05)
            ))
            log.info("QA matched topic '%s' (score=%d) for query: %s",
                     best_match, best_score, query)
            return result

        log.info("QA no match for query: %s", query)
        return {
            "answer": "I don't have enough information to answer that question "
                      "about this city. Try asking about Munich's population, "
                      "districts, transportation, landmarks, or traffic.",
            "confidence": 0.15,
            "source": "",
        }


_default_handler: UrbanQAHandler | None = None


def get_qa_handler() -> UrbanQAHandler:
    global _default_handler
    if _default_handler is None:
        _default_handler = UrbanQAHandler()
    return _default_handler


def process_query(query: str) -> dict:
    return get_qa_handler().process_query(query)
