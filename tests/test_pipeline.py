"""
Integration smoke test for the agentic pipeline.
Note: Requires litellm and a mock or real API key to fully run.
"""

import os
from agent.pipeline import Pipeline


def test_pipeline_initialization():
    """Ensure pipeline initializes without errors."""
    config = {
        "model": "test-model",
        "workspace": "/tmp/test_workspace",
        "output_dir": "/tmp/test_output",
        "candidates": 1
    }
    
    pipeline = Pipeline(config)
    assert pipeline.config["model"] == "test-model"
    assert os.path.exists("/tmp/test_output")

# Full end-to-end test is omitted as it requires network access,
# git operations, and LLM API calls which are expensive for CI.
