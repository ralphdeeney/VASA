from vasa.runtime_finalization import extractive_summary


def test_summary_quotes_intent_and_last_turn_without_claiming_success() -> None:
    messages = [{"role": "user", "content": "Please refund my order"}]
    messages += [{"role": "user", "content": f"Intermediate turn {i}"} for i in range(50)]
    messages += [
        {"role": "assistant", "content": "I completed your refund"},
        {"role": "user", "content": "Where is confirmation?"},
    ]
    summary = extractive_summary(messages)
    assert "Please refund my order" in summary and "Where is confirmation?" in summary
    assert "I completed your refund" not in summary
    assert "Resolution was not inferred" in summary


def test_empty_summary_does_not_invent_customer_or_resolution() -> None:
    assert extractive_summary([]) == (
        "No customer transcript was captured. No customer outcome was inferred."
    )


def test_summary_bounds_multiline_and_large_text() -> None:
    summary = extractive_summary([{"role": "user", "content": "word\n" * 2000}] * 1000)
    assert len(summary) <= 4000 and "\n" not in summary


def test_summary_reports_observed_tool_status_without_claiming_business_resolution() -> None:
    summary = extractive_summary(
        [{"role": "user", "content": "Please book a visit"}],
        [
            ("knowledge_search", "succeeded"),
            ("knowledge_search", "succeeded"),
            ("custom_webhook", "failed"),
            ("end_call", "pending"),
        ],
    )
    assert "knowledge_search succeeded=2" in summary
    assert "custom_webhook failed=1" in summary and "end_call pending=1" in summary
    assert "A tool status does not establish customer resolution" in summary
    assert "booked" not in summary
