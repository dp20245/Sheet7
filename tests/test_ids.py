from sheet7_pipeline.ids import event_id


def test_event_id_is_stable() -> None:
    assert event_id("SEC", "ACME", "India") == event_id(" sec ", "acme", "india")

