from __future__ import annotations

from pathlib import Path

import yaml


class AppRegistry:
    def __init__(self, config_path: str | Path = "config/apps.yaml") -> None:
        self.config_path = Path(config_path)
        self._apps = self._load_apps()

    def _load_apps(self) -> list[dict]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"App config not found: {self.config_path}")

        data = yaml.safe_load(self.config_path.read_text()) or {}
        apps = data.get("apps", [])
        if not isinstance(apps, list):
            raise ValueError("config/apps.yaml must contain a top-level 'apps' list")
        for app in apps:
            for required in ("id", "name", "description", "index"):
                if required not in app:
                    raise ValueError(f"App entry missing '{required}': {app}")
        return apps

    @property
    def apps(self) -> list[dict]:
        return self._apps

    def get_by_id(self, app_id: str) -> dict:
        for app in self._apps:
            if app["id"] == app_id:
                return app
        raise KeyError(f"Unknown app id: {app_id}")
