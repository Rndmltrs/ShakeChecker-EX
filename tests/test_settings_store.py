from settings_store import Settings


def test_defaults_to_all_visible(tmp_path):
    s = Settings.load(tmp_path)
    assert s.hidden_balls == set()
    assert s.is_ball_visible("poke")


def test_toggle_persists_and_reports_state(tmp_path):
    s = Settings.load(tmp_path)
    assert s.toggle_ball("net") is False  # now hidden
    assert not s.is_ball_visible("net")
    # reload from disk -> persisted
    assert Settings.load(tmp_path).hidden_balls == {"net"}
    assert s.toggle_ball("net") is True  # visible again
    assert Settings.load(tmp_path).hidden_balls == set()


def test_set_all(tmp_path):
    s = Settings.load(tmp_path)
    ids = ["poke", "great", "ultra"]
    s.set_all_balls(ids, visible=False)
    assert s.hidden_balls == {"poke", "great", "ultra"}
    s.set_all_balls(["poke"], visible=True)
    assert s.hidden_balls == {"great", "ultra"}
    assert Settings.load(tmp_path).hidden_balls == {"great", "ultra"}


def test_corrupt_file_falls_back(tmp_path):
    (tmp_path / "settings.json").write_text("{ not json", encoding="utf-8")
    s = Settings.load(tmp_path)
    assert s.hidden_balls == set()  # no crash, all visible
