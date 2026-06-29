from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nastech_official_theme_is_registered_and_styled() -> None:
    theme_ts = (ROOT / "frontend/src/hooks/useTheme.tsx").read_text()
    css = (ROOT / "frontend/src/index.css").read_text()
    translations = (ROOT / "frontend/src/i18n/translations.ts").read_text()
    top_bar = (ROOT / "frontend/src/components/TopBar.tsx").read_text()

    assert "'nastech-official'" in theme_ts
    assert "|| 'nastech-official'" in theme_ts
    assert "|| 'nastech-official'" in (ROOT / "frontend/src/main.tsx").read_text()
    assert "theme.nastechOfficial" in theme_ts
    assert '[data-theme="nastech-official"]' in css
    assert "--hud-bg-deep: #041c1c;" in css
    assert "--hud-primary: #ffe6cb;" in css
    assert "--hud-primary-glow: rgba(255, 189, 56, 0.35);" in css
    assert "--hud-bg: var(--hud-bg-deep);" in css
    assert "--hud-panel-alt: var(--hud-bg-surface);" in css
    assert "'theme.nastechOfficial': 'NasTech Teal'" in translations
    assert 'aria-label="Open theme picker"' in top_bar
    assert '<span className="hidden md:inline">Theme</span>' in top_bar
