"""P1-10: business API must stay independent of media/model runtimes."""
from scripts.check_architecture import find_violations


def test_business_backend_has_no_yolo_or_media_runtime_dependencies():
    assert find_violations() == []
