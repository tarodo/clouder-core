from collector.auth_handler import SPOTIFY_SCOPES


def test_scopes_include_playlist_read() -> None:
    assert "playlist-read-private" in SPOTIFY_SCOPES
    assert "playlist-read-collaborative" in SPOTIFY_SCOPES
