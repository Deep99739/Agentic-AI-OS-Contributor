#!/usr/bin/env python3
"""
Agentic AI Contributor for Open-Source Go Projects.

Usage:
    python main.py --issue https://github.com/gin-gonic/gin/issues/1234
    python main.py --issue https://github.com/gin-gonic/gin/issues/1234 --model claude-sonnet-4-20250514
"""

import argparse
import sys
import yaml
import os
from dotenv import load_dotenv

from agent.pipeline import Pipeline
from utils.logger import setup_logger, log


def main():
    # Load environment variables from .env
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Agentic AI Contributor for Open-Source Go Projects"
    )
    parser.add_argument(
        "--issue",
        required=True,
        help="GitHub issue URL (e.g., https://github.com/gin-gonic/gin/issues/1234)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model to use (overrides config.yaml). Examples: claude-sonnet-4-20250514, gpt-4.1",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=3,
        help="Number of candidate patches to generate (default: 3)",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory for output artifacts (default: ./output)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="Git commit SHA to checkout before running (e.g., parent of a known fix for testing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()

    # Load config
    config = {}
    if os.path.exists(args.config):
        with open(args.config) as f:
            config = yaml.safe_load(f) or {}

    # CLI overrides config file
    if args.model:
        config["model"] = args.model
    if "model" not in config:
        config["model"] = "claude-sonnet-4-20250514"

    # CLI --candidates overrides config only when explicitly passed
    if args.candidates != 3 or "candidates" not in config:
        config["candidates"] = args.candidates
    config["output_dir"] = args.output_dir
    config["verbose"] = args.verbose
    if args.commit:
        config["checkout_commit"] = args.commit

    setup_logger(verbose=args.verbose)

    log.info(f"🚀 Agentic AI Contributor starting...")
    log.info(f"   Issue: {args.issue}")
    log.info(f"   Model: {config['model']}")
    log.info(f"   Candidates: {config['candidates']}")

    pipeline = Pipeline(config)
    result = pipeline.run(args.issue)

    if result["success"]:
        log.info(f"✅ Success! Output saved to: {args.output_dir}")
        log.info(f"   Patch: {result['patch_file']}")
        log.info(f"   PR Summary: {result['pr_summary_file']}")
        log.info(f"   Validation: {result['validation_log']}")
    else:
        log.error(f"❌ Failed: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
