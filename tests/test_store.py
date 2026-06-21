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


def test_mark_processed_dedupes_message_id(tmp_path):
    store = Store(tmp_path / "t.db")
    # First delivery is claimed; any retry of the same id is rejected.
    assert store.mark_processed("wamid.ABC") is True
    assert store.mark_processed("wamid.ABC") is False
    # A different id is still processed.
    assert store.mark_processed("wamid.DEF") is True


def test_mark_processed_treats_falsy_id_as_always_new(tmp_path):
    # /simulate has no message id — it must never be deduped.
    store = Store(tmp_path / "t.db")
    assert store.mark_processed(None) is True
    assert store.mark_processed(None) is True
    assert store.mark_processed("") is True
