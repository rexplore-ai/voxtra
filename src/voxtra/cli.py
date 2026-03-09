"""Voxtra CLI — command-line interface for managing Voxtra applications.

Usage:
    voxtra start              Start the Voxtra application
    voxtra start -c config    Start with a specific config file
    voxtra init               Generate a starter voxtra.yaml
    voxtra info               Show Voxtra version and config info
    voxtra check              Validate configuration
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import voxtra


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="voxtra",
        description="Voxtra — Open voice infrastructure for AI agents",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"voxtra {voxtra.__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- start ---
    start_parser = subparsers.add_parser("start", help="Start the Voxtra application")
    start_parser.add_argument(
        "-c", "--config",
        default="voxtra.yaml",
        help="Path to configuration file (default: voxtra.yaml)",
    )
    start_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    # --- init ---
    init_parser = subparsers.add_parser("init", help="Generate a starter voxtra.yaml")
    init_parser.add_argument(
        "-o", "--output",
        default="voxtra.yaml",
        help="Output file path (default: voxtra.yaml)",
    )

    # --- info ---
    subparsers.add_parser("info", help="Show Voxtra version and system info")

    # --- check ---
    check_parser = subparsers.add_parser("check", help="Validate configuration")
    check_parser.add_argument(
        "-c", "--config",
        default="voxtra.yaml",
        help="Path to configuration file (default: voxtra.yaml)",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        _cmd_start(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "info":
        _cmd_info()
    elif args.command == "check":
        _cmd_check(args)


def _cmd_start(args: argparse.Namespace) -> None:
    """Start the Voxtra application from a config file."""
    from voxtra.app import VoxtraApp
    from voxtra.config import VoxtraConfig

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        print("Run 'voxtra init' to generate a starter config.")
        sys.exit(1)

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        config = VoxtraConfig.from_yaml(config_path)
        if args.debug:
            config.server.debug = True

        app = VoxtraApp(config=config)
        print(f"Starting Voxtra '{config.app_name}' from {config_path}")
        app.run()
    except Exception as exc:
        print(f"Error starting Voxtra: {exc}")
        sys.exit(1)


def _cmd_init(args: argparse.Namespace) -> None:
    """Generate a starter voxtra.yaml configuration file."""
    from voxtra.config import VoxtraConfig

    output_path = Path(args.output)
    if output_path.exists():
        print(f"Error: File already exists: {output_path}")
        sys.exit(1)

    config = VoxtraConfig(app_name="my-call-center")
    config.to_yaml(output_path)
    print(f"Generated starter config: {output_path}")
    print("Edit the file to add your API keys and Asterisk settings.")


def _cmd_info() -> None:
    """Show Voxtra version and system information."""
    import platform

    print(f"Voxtra {voxtra.__version__}")
    print(f"Python {platform.python_version()}")
    print(f"Platform: {platform.platform()}")

    # Check optional dependencies
    deps = {
        "asyncari": "Asterisk ARI",
        "livekit": "LiveKit",
        "deepgram": "Deepgram STT",
        "openai": "OpenAI LLM",
        "elevenlabs": "ElevenLabs TTS",
    }
    print("\nProvider availability:")
    for module, label in deps.items():
        try:
            __import__(module)
            print(f"  ✓ {label}")
        except ImportError:
            print(f"  ✗ {label} (not installed)")


def _cmd_check(args: argparse.Namespace) -> None:
    """Validate a Voxtra configuration file."""
    from voxtra.config import VoxtraConfig

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    try:
        config = VoxtraConfig.from_yaml(config_path)
        print(f"✓ Configuration valid: {config_path}")
        print(f"  App name: {config.app_name}")
        print(f"  Telephony: {config.telephony.provider}")
        print(f"  STT: {config.ai.stt.provider}")
        print(f"  LLM: {config.ai.llm.provider}")
        print(f"  TTS: {config.ai.tts.provider}")
        print(f"  Routes: {len(config.routes)}")
    except Exception as exc:
        print(f"✗ Configuration error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
