import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="SteamGifts Bot WebUI")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8765")),
    )
    args = parser.parse_args()

    uvicorn.run(
        "web.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
