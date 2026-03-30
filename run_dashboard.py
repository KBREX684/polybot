from __future__ import annotations

from src.polybot.config import Settings
from src.polybot.ui.app import create_app


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings=settings)
    app.run(host=settings.dashboard_host, port=settings.dashboard_port, debug=False)


if __name__ == "__main__":
    main()
