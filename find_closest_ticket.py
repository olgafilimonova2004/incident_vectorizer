"""Find the incident whose stored embedding is closest to supplied text."""

import argparse
import json
import sys
from typing import Any

import httpx

from src.common.config import EmbedderConfig, VespaConfig
from src.services.embedder_service import EmbedderService


def find_closest_ticket(
    text: str,
    *,
    embedder_config: EmbedderConfig | None = None,
    vespa_config: VespaConfig | None = None,
) -> dict[str, Any] | None:
    """Embed description/comments and return the nearest Vespa incident hit."""
    if not text.strip():
        raise ValueError("Description and comments must contain some text")

    embedder = EmbedderService(embedder_config or EmbedderConfig())
    try:
        vector = embedder.embed_texts([text])[0]
    finally:
        embedder.close()

    vespa = vespa_config or VespaConfig()
    query = {
        "yql": (
            "select ticket_id, text, status, updated_at_jira from incident "
            "where {targetHits:1,approximate:false}nearestNeighbor(embedding,q_embedding)"
        ),
        "hits": 1,
        "ranking": "semantic",
        "input": {"query(q_embedding)": vector},
    }
    with httpx.Client(base_url=str(vespa.url).rstrip("/") + "/", timeout=vespa.timeout) as client:
        response = client.post("search/", json=query)
        if response.is_error:
            raise RuntimeError(f"Vespa search failed (HTTP {response.status_code}): {response.text}")
        result = response.json()

    errors = result.get("root", {}).get("errors") or result.get("errors")
    if errors:
        raise RuntimeError(f"Vespa search failed: {errors}")
    if result.get("root", {}).get("coverage", {}).get("full") is False:
        raise RuntimeError("Vespa search returned partial coverage")

    children = result.get("root", {}).get("children", [])
    if not children:
        return None
    hit = children[0]
    return {"relevance": hit["relevance"], **hit["fields"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Find the closest indexed incident")
    parser.add_argument("text", help="Description and comments as one string; use - to read stdin")
    parser.add_argument("--vespa-url", help="Override INCIDENT_VESPA_URL")
    parser.add_argument("--embedder-url", help="Override INCIDENT_EMBEDDER_BASE_URL")
    args = parser.parse_args()
    text = sys.stdin.read() if args.text == "-" else args.text
    try:
        vespa = VespaConfig(url=args.vespa_url) if args.vespa_url else VespaConfig()
        embedder = EmbedderConfig(base_url=args.embedder_url) if args.embedder_url else EmbedderConfig()
        ticket = find_closest_ticket(text, vespa_config=vespa, embedder_config=embedder)
    except (ValueError, httpx.HTTPError, RuntimeError, KeyError) as exc:
        parser.exit(1, f"Search failed: {exc}\n")
    print(json.dumps(ticket, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
