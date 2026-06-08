"""
Integration smoke test for the agentic pipeline.
Note: Requires litellm and a mock or real API key to fully run.
"""

import os
import tempfile
from agent.pipeline import Pipeline


def test_pipeline_initialization():
    """Ensure pipeline initializes without errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "model": "test-model",
            "workspace": os.path.join(tmpdir, "workspace"),
            "output_dir": os.path.join(tmpdir, "output"),
            "candidates": 1,
        }

        pipeline = Pipeline(config)
        assert pipeline.config["model"] == "test-model"
        assert os.path.exists(config["output_dir"])
        # Verify system prompt was injected
        assert "system_prompt" in pipeline.config
        assert len(pipeline.config["system_prompt"]) > 0


# Full end-to-end test is omitted as it requires network access,
# git operations, and LLM API calls which are expensive for CI.
