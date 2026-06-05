"""
Phase 3: Generate multiple candidate patches using SEARCH/REPLACE blocks.
"""

from utils.llm_client import LLMClient
from utils.patch import parse_search_replace_blocks, apply_patches
from utils.logger import log
from agent.prompts.repair import REPAIR_PROMPT


class Repairer:
    """Generates and parses candidate code patches."""

    def __init__(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self.llm = LLMClient(config)

    def generate_patches(
        self,
        issue_data: dict,
        repo_map: str,
        localization: dict,
        num_candidates: int = 3,
    ) -> list:
        """
        Generate multiple candidate patches via LLM at varying temperatures.
        Returns a list of candidate dictionaries.
        """
        candidates = []

        # Build the code context string for the LLM
        file_contents_str = ""
        for fpath, content in localization["file_contents"].items():
            file_contents_str += f"\n\n--- FILE: {fpath} ---\n```go\n{content}\n```\n"

        for i in range(num_candidates):
            log.info(f"Generating candidate patch {i+1}/{num_candidates}...")

            # Vary temperature for diversity: 0.0, 0.2, 0.4...
            # The first candidate (0.0) is the most greedy/deterministic
            temperature = 0.0 + (i * 0.2)

            prompt = REPAIR_PROMPT.format(
                issue_title=issue_data["title"],
                issue_body=(issue_data.get("body") or "")[:5000],
                element_analysis=localization.get("elements", "")[:3000],
                file_contents=file_contents_str[:40000],  # ~10k tokens max
                repo_map_snippet=repo_map[:5000],
            )

            # Generate fix
            response = self.llm.chat(prompt, temperature=temperature)

            # Extract SEARCH/REPLACE blocks
            patches = parse_search_replace_blocks(response)

            if patches:
                candidates.append(
                    {
                        "index": i,
                        "patches": patches,
                        "raw_response": response,
                        "temperature": temperature,
                    }
                )
                log.info(f"  Candidate {i+1}: {len(patches)} edit(s) parsed")
            else:
                log.warning(f"  Candidate {i+1}: No valid SEARCH/REPLACE blocks found")

        return candidates

    def apply_patch(self, candidate: dict) -> list:
        """
        Apply a candidate's patches to the actual files in the repository.
        Returns a list of application results.
        """
        return apply_patches(self.repo_path, candidate["patches"])
