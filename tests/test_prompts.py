from types import SimpleNamespace

from common import prompts


def test_agent_specific_prompt_version_override(tmp_path, monkeypatch):
    for agent in ("classifier", "compliance", "verifier"):
        folder = tmp_path / agent
        folder.mkdir()
        (folder / "v1.md").write_text(f"{agent} baseline {{ {{ bid }} }}")
        (folder / "v2.md").write_text(f"{agent} candidate {{ {{ bid }} }}")

    monkeypatch.setattr(
        prompts,
        "get_settings",
        lambda: SimpleNamespace(prompts_dir=str(tmp_path), prompt_version="v1"),
    )
    monkeypatch.setenv("COMPLIANCE_PROMPT_VERSION", "v2")

    compliance_text, compliance_version = prompts.load_prompt("compliance", bid="BID-1")
    classifier_text, classifier_version = prompts.load_prompt("classifier", bid="BID-1")
    verifier_text, verifier_version = prompts.load_prompt("verifier", bid="BID-1")

    assert compliance_version == "compliance/v2"
    assert classifier_version == "classifier/v1"
    assert verifier_version == "verifier/v1"
    assert "candidate" in compliance_text
    assert "baseline" in classifier_text
    assert "baseline" in verifier_text
