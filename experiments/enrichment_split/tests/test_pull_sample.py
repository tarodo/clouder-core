from splitlab.config import Settings
from splitlab.pull_sample import pull

SETTINGS = Settings(openai_api_key="x", tavily_api_key="y")


def fake_execute_factory(rows_by_marker):
    calls = []

    def execute(sql: str):
        calls.append(sql)
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                return rows
        return []

    return execute, calls


def test_pull_builds_strata_and_baseline():
    label_row = {
        "id": "l1", "name": "Defiant", "style": "dnb",
        "merged": '{"instagram_url": null, "website": "https://d.example"}',
    }
    artist_row = {
        "id": "a1", "name": "Vision", "style": "dnb",
        "merged": '{"instagram_url": "https://www.instagram.com/v"}',
        "sample_tracks": "Deep|Deeper", "known_labels": "Hospital Records",
    }
    execute, calls = fake_execute_factory({
        "clouder_label_info": [label_row],
        "clouder_artist_info": [artist_row],
    })
    data = pull(SETTINGS, execute=execute, labels=2, artists=2)
    assert data["labels"][0]["name"] == "Defiant"
    assert data["labels"][0]["baseline"]["website"] == "https://d.example"
    assert data["artists"][0]["sample_tracks"] == ["Deep", "Deeper"]
    assert data["artists"][0]["known_labels"] == ["Hospital Records"]
    # two strata per kind -> 4 SELECTs
    assert sum("instagram_url" in c for c in calls) >= 2
