from physiobot.store import Store


def test_history_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add_message("p1", "user", "hello")
    store.add_message("p1", "assistant", "hi there")
    store.add_message("p2", "user", "other")

    hist = store.history("p1")
    assert hist == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_history_limit_keeps_recent(tmp_path):
    store = Store(tmp_path / "t.db")
    for i in range(10):
        store.add_message("p", "user", f"m{i}")
    hist = store.history("p", limit=3)
    assert [m["content"] for m in hist] == ["m7", "m8", "m9"]


def test_touch_session(tmp_path):
    store = Store(tmp_path / "t.db")
    store.touch_session("p")
    store.touch_session("p")  # upsert, no error
