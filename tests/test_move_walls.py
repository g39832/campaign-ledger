"""Players can't drag through walls, but a drag around a corner or through a doorway works, the same
whichever squares it starts on (no odd/even rounding luck)."""
from app.maps import blocked_path


def _m(walls):
    return {"terrain": {f"{x},{y}": "wall" for x, y in walls}}


def test_straight_through_a_wall_is_refused():
    wall = [(5, y) for y in range(0, 20)]  # a long wall with no gap
    assert blocked_path(_m(wall), 1, 3, 5, 7, 5)
    assert blocked_path(_m(wall), 1, 4, 4, 6, 6)


def test_around_a_corner_or_through_a_doorway_is_fine():
    # a wall with a doorway at y=10: from beside the doorway to the far side at an angle
    wall = [(5, y) for y in range(0, 20) if y != 10]
    assert blocked_path(_m(wall), 1, 4, 10, 6, 12) is None
    assert blocked_path(_m(wall), 1, 3, 8, 7, 11) is None
    # the end of a wall: round its tip
    tip = [(5, y) for y in range(0, 10)]
    assert blocked_path(_m(tip), 1, 4, 8, 6, 9) is None


def test_the_same_move_works_on_any_square():
    # one square diagonally past a wall's corner, starting on even and odd squares alike
    for sx in range(2, 8):
        for sy in range(2, 8):
            walls = [(sx + 1, sy)]  # a single pillar beside the hero
            assert blocked_path(_m(walls), 1, sx, sy, sx + 1, sy + 1) is None, (sx, sy)


def test_no_squeezing_between_two_walls_touching_at_a_corner():
    walls = [(5, 5), (6, 6)] + [(5, y) for y in range(0, 5)] + [(6, y) for y in range(7, 20)] + [(x, 5) for x in range(0, 5)] + [(x, 6) for x in range(7, 20)]
    assert blocked_path(_m(walls), 1, 6, 5, 5, 6)


def test_a_far_room_behind_a_long_wall_is_still_refused():
    wall = [(5, y) for y in range(0, 40) if y != 30]  # the only gap is far away
    assert blocked_path(_m(wall), 1, 4, 5, 6, 5)


def test_onto_a_wall_is_refused():
    assert blocked_path(_m([(6, 5)]), 1, 4, 5, 6, 5)


def test_the_way_round_stays_on_the_map():
    rock = {"terrain": {"2,0": "rock", "2,1": "rock", "2,2": "rock"}, "cols": 20, "rows": 20}
    assert blocked_path(rock, 1, 0, 0, 4, 0)  # no slipping round above the top edge
