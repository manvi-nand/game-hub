from app.llm_prompts import (
    TruthOrDareBatchRequest,
    build_truth_or_dare_batch_prompt,
    clean_prompt_batch,
    clean_prompt,
    generate_truth_or_dare_batch,
)


def test_build_truth_or_dare_batch_prompt_includes_game_context_and_safety_rules():
    prompt = build_truth_or_dare_batch_prompt(
        TruthOrDareBatchRequest(
            scenario="college friends reunion",
            intensity="wild",
            mode="mixed",
            prompt_type="dare",
            player_names=["Maya", "Sam"],
            used_prompts=["Do a dance."],
            count=50,
        )
    )

    assert "50 unique dare prompts" in prompt
    assert "college friends reunion" in prompt
    assert "wild" in prompt
    assert "dare" in prompt
    assert "Maya" in prompt
    assert "Do a dance." in prompt
    assert "physically safe" in prompt
    assert "non-explicit" in prompt


def test_clean_prompt_removes_label_and_truncates():
    cleaned = clean_prompt('Truth:   Tell everyone your favorite snack.   ')

    assert cleaned == "Tell everyone your favorite snack."


def test_clean_prompt_batch_parses_json_and_dedupes():
    prompts = clean_prompt_batch(
        '{"prompts":["Truth: Tell a joke.","Tell a joke.","2. Do a pose."]}',
        10,
    )

    assert prompts == ["Tell a joke.", "Do a pose."]


def test_generate_truth_or_dare_batch_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = generate_truth_or_dare_batch(
        TruthOrDareBatchRequest(
            scenario="",
            intensity="mild",
            mode="truth",
            prompt_type="truth",
            player_names=["Maya"],
            used_prompts=[],
        )
    )

    assert result == []
