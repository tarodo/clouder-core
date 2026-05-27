import json
import collector.artist_enrichment.auto_dispatch as ad
from collector.artist_enrichment.repository import RunSpec


class FakeAutoRepo:
    def __init__(self, enabled=True, claim=None, ids_for_track=None, ids_for_block=None):
        self._cfg = {"enabled": enabled, "prompt_slug": "artist_v1", "prompt_version": "v1",
                     "vendors": ["openai"], "models": {"openai": "m"},
                     "merge_vendor": "deepseek", "merge_model": "d"} if enabled else {"enabled": False}
        self._claim = claim if claim is not None else []
        self._ids_for_track = ids_for_track or []
        self._ids_for_block = ids_for_block or []
        self.attached = None
    def get_config(self, kind): assert kind == "artists"; return self._cfg
    def claim_artists(self, ids): return list(self._claim)
    def attach_run(self, ids, run_id): self.attached = (list(ids), run_id)
    def artist_ids_for_track(self, track_id): return list(self._ids_for_track)
    def artist_ids_for_triage_block(self, block_id): return list(self._ids_for_block)


class FakeArtistRepo:
    def __init__(self): self.created = None
    def get_artist_by_id(self, aid): return {"id": aid, "name": f"name-{aid}"}
    def create_run(self, spec): self.created = spec; return "run-1"


class FakeSQS:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def _wire(monkeypatch, auto_repo, artist_repo=None, sqs=None):
    artist_repo = artist_repo or FakeArtistRepo()
    sqs = sqs or FakeSQS()
    monkeypatch.setattr(ad, "_build_auto_repository", lambda: auto_repo)
    monkeypatch.setattr(ad, "_build_artist_repository", lambda: artist_repo)
    monkeypatch.setattr(ad, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(ad, "_queue_url", lambda: "https://q")
    return artist_repo, sqs


def test_disabled_config_skips(monkeypatch):
    auto = FakeAutoRepo(enabled=False)
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1"], source_hint="single", user_id="u")
    assert sqs.sent == [] and artist_repo.created is None


def test_no_claim_skips_enqueue(monkeypatch):
    auto = FakeAutoRepo(enabled=True, claim=[])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1"], source_hint="single", user_id="u")
    assert sqs.sent == [] and artist_repo.created is None


def test_happy_path_creates_run_and_enqueues_per_artist(monkeypatch):
    auto = FakeAutoRepo(enabled=True, claim=["a1", "a2"])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1", "a2"], source_hint="single", user_id="u")
    assert isinstance(artist_repo.created, RunSpec)
    assert artist_repo.created.requested_artists == 2
    assert artist_repo.created.source == "auto"
    assert auto.attached == (["a1", "a2"], "run-1")
    assert len(sqs.sent) == 2
    msg = json.loads(sqs.sent[0]["MessageBody"])
    assert msg["run_id"] == "run-1" and msg["artist_id"] == "a1" and msg["artist_name"] == "name-a1"
    assert "style" not in msg


def test_track_dispatch_resolves_all_roles(monkeypatch):
    # artist_ids_for_track returns MULTIPLE artists (all roles)
    auto = FakeAutoRepo(enabled=True, claim=["a1", "a2", "a3"], ids_for_track=["a1", "a2", "a3"])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad.try_dispatch_artists_for_track(track_id="t1", user_id="u")
    assert len(sqs.sent) == 3


def test_dispatch_never_raises(monkeypatch):
    def boom(): raise RuntimeError("db down")
    monkeypatch.setattr(ad, "_build_auto_repository", boom)
    # must not raise
    ad.try_dispatch_artists_for_track(track_id="t1", user_id="u")
    ad.try_dispatch_artists_for_triage_block(block_id="b1", user_id="u")
