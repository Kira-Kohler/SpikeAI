import copy
import json
import os
import math
import re
import shutil
from pathlib import Path
from .package import package_family_name, package_home

DEFAULTS = {
    "version": 3,
    "monitor": "auto",
    "volume": 0.65,
    "muted": False,
    "debug": False,
    "overlay_position": None,
    "detection_enabled": True,
    "absence_watch": True,
    "start_minimized": False,
    "minimize_to_tray": True,
    "tray_notifications": True,
    "startup": False,
    "hotkey": "f7",
    "cancel_hotkey": "f8",
    "design_revision": 3,
    "animation_intensity": 0.7,
    "high_contrast": False,
    "overlay_scale": 1.0,
    "overlay_opacity": 0.92,
    "overlay_compact": True,
    "animations": True,
    "edge_enabled": True,
    "edge_intensity": 0.65,
    "edge_opacity": 0.32,
    "edge_speed": 0.7,
    "edge_thickness": 48,
    "edge_color": "#ff4655",
    "edge_threshold": 5,
    "edge_animations": True,
    "agent": "jett",
    "theme": "Phoenix",
    "accent": "#ff4655",
    "effects": True,
    "voice_enabled": {},
    "voice_files": {},
    "log_path": r"%LOCALAPPDATA%\Valorant\Saved\Logs\ShooterGame.log",
    "log_autoscroll": True,
}


LEGACY_HOME = "SpikeIA3"


def migrate_legacy_home(home, legacy):
    if home.exists() or not legacy.is_dir():
        return
    try:
        os.replace(legacy, home)
    except OSError:
        shutil.copytree(legacy, home)
    for log in sorted(home.glob("SpikeIA.log*")):
        target = home / log.name.replace("SpikeIA", "SpikeAI", 1)
        if not target.exists():
            try:
                log.replace(target)
            except OSError:
                pass
    rebase_voice_files(home, legacy)


def rebase_voice_files(home, source):
    path = home / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    files = data.get("voice_files")
    if not isinstance(files, dict):
        return
    old = os.path.normcase(str(source)) + os.sep
    moved = {
        k: str(home) + v[len(old) - 1 :] if isinstance(v, str) and os.path.normcase(v).startswith(old) else v
        for k, v in files.items()
    }
    if moved != files:
        data["voice_files"] = moved
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def import_home(home, sources):
    if (home / "config.json").exists():
        return None
    source = next((s for s in sources if (s / "config.json").is_file()), None)
    if source is None:
        return None
    home.mkdir(parents=True, exist_ok=True)
    voices = source / "voices"
    if voices.is_dir():
        (home / "voices").mkdir(exist_ok=True)
        for wav in voices.glob("*.wav"):
            target = home / "voices" / wav.name
            if not target.exists():
                shutil.copy2(wav, target)
    shutil.copy2(source / "config.json", home / "config.json")
    rebase_voice_files(home, source)
    return source


def default_home():
    roaming = Path(os.environ.get("APPDATA", Path.home())) / "SpikeAI3"
    try:
        family = package_family_name()
    except OSError:
        family = None
    if family:
        return package_home(family), roaming
    return roaming, None


class Config:
    def __init__(self, home=None):
        self.imported_from = None
        if home or os.environ.get("SPIKEAI_HOME"):
            self.home = Path(home or os.environ.get("SPIKEAI_HOME"))
        else:
            self.home, standalone = default_home()
            try:
                if standalone is None:
                    migrate_legacy_home(self.home, self.home.with_name(LEGACY_HOME))
                else:
                    self.imported_from = import_home(
                        self.home, [standalone, standalone.with_name(LEGACY_HOME)]
                    )
            except OSError:
                pass
        self.path = self.home / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update({k: user[k] for k in DEFAULTS if k in user})
                revision = user.get("design_revision", 0)
                if not isinstance(revision, (int, float)):
                    revision = 0
                if revision < 2:
                    self.data["theme"] = "Phoenix"
                    self.data["accent"] = "#ff4655"
                    if self.data["hotkey"] in ("º", "Âº"):
                        self.data["hotkey"] = "f7"
                if revision < 3:
                    self.data["overlay_compact"] = True
                self.data["design_revision"] = DEFAULTS["design_revision"]
                self.data["volume"] = min(1, max(0, float(self.data["volume"])))
                self.data["version"] = 3
                self.validate()
            except (ValueError, TypeError, OSError):
                self.data = copy.deepcopy(DEFAULTS)

    def validate(self):
        for key, default in DEFAULTS.items():
            if isinstance(default, bool) and not isinstance(self.data[key], bool):
                self.data[key] = default
        bounds = {
            "volume": (0, 1),
            "animation_intensity": (0, 1),
            "overlay_scale": (0.7, 1.8),
            "overlay_opacity": (0.3, 1),
            "edge_intensity": (0.1, 1),
            "edge_opacity": (0.05, 0.65),
            "edge_speed": (0.2, 1.5),
            "edge_thickness": (12, 100),
        }
        for key, (lo, hi) in bounds.items():
            try:
                value = float(self.data[key])
                self.data[key] = max(lo, min(hi, value)) if math.isfinite(value) else DEFAULTS[key]
            except (ValueError, TypeError):
                self.data[key] = DEFAULTS[key]
        self.data["edge_thickness"] = int(self.data["edge_thickness"])
        for key, choices in {
            "agent": ("jett", "viper", "phoenix", "none"),
            "theme": ("Phoenix", "Reyna", "Viper", "Neon", "Chamber", "Clove", "RGB", "Obsidian"),
            "edge_threshold": (3, 5, 10),
        }.items():
            if self.data[key] not in choices:
                self.data[key] = DEFAULTS[key]
        for key in ("accent", "edge_color"):
            if not isinstance(self.data[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.data[key]):
                self.data[key] = DEFAULTS[key]
        for key in ("voice_enabled", "voice_files"):
            if not isinstance(self.data[key], dict):
                self.data[key] = {}
        self.data["voice_files"] = {k: v for k, v in self.data["voice_files"].items() if isinstance(v, str)}
        self.data["voice_enabled"] = {
            k: v for k, v in self.data["voice_enabled"].items() if isinstance(v, bool)
        }
        position = self.data["overlay_position"]
        if position is not None and not (
            isinstance(position, list)
            and len(position) == 2
            and all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < 100000 for v in position)
        ):
            self.data["overlay_position"] = None
        for key in ("hotkey", "cancel_hotkey", "log_path"):
            if not isinstance(self.data[key], str) or not self.data[key].strip():
                self.data[key] = DEFAULTS[key]
        if not isinstance(self.data["monitor"], (int, str)):
            self.data["monitor"] = "auto"

    def save(self):
        self.home.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp.replace(self.path)
