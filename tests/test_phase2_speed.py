"""A boss's speed line can give it a phase 2 speed: Steven Voss walks 30 ft, and from half HP his steel
wings give him 90 ft of movement ("30 ft. (fly 90 ft. in phase 2)")."""
import json

from app import movement, voss


class Row(dict):
    def keys(self):
        return list(super().keys())


def row(hp, mx=350, speed=voss.STEVEN["speed"], phase2=True, conds=()):
    return Row(statblock=json.dumps({"speed": speed, "has_phase2": phase2}), conditions=json.dumps(list(conds)), current_hp=hp, max_hp=mx)


def test_steven_code_numbers():
    assert voss.STEVEN["max_hp"] == 350
    assert movement.PHASE2_SPEED.search(voss.STEVEN["speed"]).group(1) == "90"


def test_phase_one_walks_30():
    assert movement.monster_speed(row(350)) == 30
    assert movement.monster_speed(row(176)) == 30


def test_phase_two_moves_90():
    assert movement.monster_speed(row(175)) == 90
    assert movement.monster_speed(row(1)) == 90


def test_down_or_no_phase2_keeps_base():
    assert movement.monster_speed(row(0)) == 30
    assert movement.monster_speed(row(100, phase2=False)) == 30
    assert movement.monster_speed(row(100, speed="40 ft., fly 80 ft.")) == 40


def test_slowed_still_halves_it():
    assert movement.monster_speed(row(100, conds=[{"name": "Slowed", "slowed": True}])) == 45
