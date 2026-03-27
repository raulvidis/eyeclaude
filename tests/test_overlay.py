from eyeclaude.overlay import compute_quadrant_rect
from eyeclaude.shared_state import Quadrant


class TestComputeQuadrantRect:
    def test_top_left(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_LEFT, 1920, 1080)
        assert x == 0
        assert y == 0
        assert w == 960
        assert h == 540

    def test_top_right(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_RIGHT, 1920, 1080)
        assert x == 960
        assert y == 0
        assert w == 960
        assert h == 540

    def test_bottom_left(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.BOTTOM_LEFT, 1920, 1080)
        assert x == 0
        assert y == 540
        assert w == 960
        assert h == 540

    def test_bottom_right(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.BOTTOM_RIGHT, 1920, 1080)
        assert x == 960
        assert y == 540
        assert w == 960
        assert h == 540

    def test_odd_resolution(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_LEFT, 1921, 1081)
        assert x == 0
        assert y == 0
        assert w == 960
        assert h == 540
