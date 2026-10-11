from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    title: str
    agent: str
    accent: str
    secondary: str
    background: str
    surface: str
    motif: str
    slogan: str


THEMES = {
    "Phoenix": Theme(
        "INFERNO", "phoenix", "#ff4655", "#ffb05c", "#110f14", "#211820", "fire", "IGNITE THE MOMENT"
    ),
    "Reyna": Theme("EMPRESS", "reyna", "#c66af5", "#fc76c3", "#110d1b", "#21172c", "orb", "OWN THE MOMENT"),
    "Viper": Theme(
        "TOXIC", "viper", "#51dc95", "#a5e965", "#0c1514", "#162520", "chemical", "CONTROL THE FIELD"
    ),
    "Neon": Theme(
        "OVERCHARGE", "neon", "#58cfff", "#ffe18a", "#0c1220", "#162238", "electric", "AHEAD OF THE CLOCK"
    ),
    "Chamber": Theme(
        "GOLDEN PRECISION",
        "chamber",
        "#d4b67a",
        "#f2e5c8",
        "#0c111b",
        "#181f2b",
        "precision",
        "PRECISION IS EVERYTHING",
    ),
    "Clove": Theme(
        "AFTERLIFE", "clove", "#f27ac8", "#b49cff", "#120d17", "#22182a", "butterfly", "NOT DEAD YET"
    ),
    "RGB": Theme(
        "SPECTRUM", "", "#a998ff", "#55e5ed", "#101019", "#20202e", "spectrum", "EVERY SECOND COUNTS"
    ),
    "Obsidian": Theme(
        "SHADOW", "", "#c6d1dd", "#7a8da2", "#0d1016", "#1a1e26", "shadow", "FOCUS ON THE MOMENT"
    ),
}


def theme(config):
    return THEMES.get(config.get("theme"), THEMES["Phoenix"])
