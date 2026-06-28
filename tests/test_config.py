import pytest

from trip_albums.config import load_config, ConfigError


def base_env(**overrides):
    env = {
        "IMMICH_URL": "https://immich.example.com",
        "IMMICH_API_KEY": "secret",
        "HOME_CITIES": "Paris, Lyon",
        "HOME_COUNTRIES": "France",
        "GAP_MIN_DAYS": "1.5",
        "GAP_MAX_DAYS": "6",
        "TRIP_GAP_FALLBACK_DAYS": "4",
        "OUTLIER_MAX_ASSETS": "2",
        "REVIEW_TAG": "needs-location-review",
        "ALBUM_PREFIX": "Trip — ",
    }
    env.update(overrides)
    return env


def test_parses_lists_lowercased_and_trimmed():
    cfg = load_config(base_env())
    assert cfg.home_cities == ["paris", "lyon"]
    assert cfg.home_countries == ["france"]


def test_missing_url_raises():
    env = base_env()
    del env["IMMICH_URL"]
    with pytest.raises(ConfigError):
        load_config(env)


def test_missing_api_key_raises():
    env = base_env()
    del env["IMMICH_API_KEY"]
    with pytest.raises(ConfigError):
        load_config(env)


def test_threshold_order_validated():
    with pytest.raises(ConfigError):
        load_config(base_env(TRIP_GAP_FALLBACK_DAYS="9"))  # > GAP_MAX


def test_home_coords_all_or_nothing():
    with pytest.raises(ConfigError):
        load_config(base_env(HOME_LAT="48.8"))  # lon missing


def test_home_coords_parsed_when_both_present():
    cfg = load_config(base_env(HOME_LAT="48.8566", HOME_LON="2.3522", HOME_RADIUS_KM="25"))
    assert cfg.home_lat == 48.8566 and cfg.home_lon == 2.3522
    assert cfg.home_radius_km == 25.0
    assert cfg.has_home_coords is True


def test_llm_disabled_without_key():
    cfg = load_config(base_env())
    assert cfg.llm_enabled is False


def test_llm_enabled_with_key_unless_no_llm():
    cfg = load_config(base_env(ANTHROPIC_API_KEY="sk-ant"))
    assert cfg.llm_enabled is True
    cfg2 = load_config(base_env(ANTHROPIC_API_KEY="sk-ant"), no_llm=True)
    assert cfg2.llm_enabled is False


def test_url_trailing_slash_stripped():
    cfg = load_config(base_env(IMMICH_URL="https://immich.example.com/"))
    assert cfg.immich_url == "https://immich.example.com"
