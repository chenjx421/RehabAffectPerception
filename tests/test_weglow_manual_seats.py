from rehab_affect.demo2_student_tracking import _manual_seats
from rehab_affect.demo2_person_filter import apply_person_filter


def test_manual_seats_are_sorted_and_normalized():
    seats = _manual_seats([
        {'x': .5, 'y': .4, 'width': .1, 'height': .2},
        {'x': .1, 'y': .5, 'width': .1, 'height': .2},
    ])
    assert [round(s['x'], 2) for s in seats] == [.1, .5]


def test_manual_seat_person_is_not_removed_by_auto_filter():
    analysis = {
        'persons': [{
            'person_id': 'person_01', 'manual_seat': True, 'anchor_bbox': {'x': .1, 'y': .5, 'width': .1, 'height': .2},
            'person_filter': {'status': 'blank', 'auto_status': 'blank', 'reasons': ['small_face']},
        }],
        'excluded_persons': [],
    }
    result = apply_person_filter(analysis)
    assert [p['person_id'] for p in result['persons']] == ['person_01']
    assert result['persons'][0]['person_filter']['status'] == 'student'
    assert result['excluded_persons'] == []
