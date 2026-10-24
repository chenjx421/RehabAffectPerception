"""Print response structure only, never provider prose or request/credentials."""
import json
import re
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    if root.parent != Path('/var/lib/rehabaffect/acceptance-private') or root.is_symlink():
        raise ValueError('private_directory_required')
    reports = []
    for path in sorted(root.glob('provider-response-*.private.json')):
        if path.is_symlink() or path.stat().st_size > 262144:
            continue
        report = {'file': path.name}
        try:
            envelope = json.loads(path.read_bytes())
            choice = envelope['choices'][0]
            report['stopped'] = choice.get('finish_reason') == 'stop'
            report['truncated'] = choice.get('finish_reason') == 'length'
            content = choice['message'].get('content')
            report['content_string'] = isinstance(content, str)
            value = json.loads(content)
            report['root_key_categories'] = [key if key in {'frames','error','message','detail','code','status','result','data','reason','observations'} else 'other'
                for key in value.keys()] if isinstance(value,dict) else ['not_object']
            report['bounded_root_field_names'] = [key for key in value if re.fullmatch('[a-z_]{1,30}',key)] if isinstance(value,dict) else []
            if isinstance(value,dict) and set(value) != {'frames'}:
                lowered = json.dumps(value, ensure_ascii=False).lower()
                report['failure_keyword_categories'] = [word for word in ('rate','limit','balance','quota','credit','unsupported','image','model','timeout','error','invalid') if word in lowered]
            report['frames_root'] = isinstance(value,dict) and set(value) == {'frames'}
            report['frames'] = []
            for frame in value.get('frames', [])[:8]:
                rows = frame.get('observations', [])
                boxes = [row.get('person_index', row.get('bbox')) for row in rows]
                report['frames'].append({'time': frame.get('timestamp_sec'), 'observations': len(rows),
                    'localized': sum(box is not None for box in boxes),
                    'distinct_boxes': len({json.dumps(box,sort_keys=True) for box in boxes if box is not None}),
                    'unknown_behavior_count': sum(row.get('behavior') not in {
                        'hand_raised','writing','manipulating_materials','handing_materials','receiving_materials',
                        'head_toward_materials','head_toward_visible_person','head_toward_camera',
                        'head_away_from_materials','seated','standing','walking','out_of_seat'} for row in rows),
                    'exact_row_fields': all(set(row) in ({'behavior','bbox'}, {'behavior','person_index'}) for row in rows),
                    'temporal_actions': sum(row.get('behavior') in {'walking','out_of_seat'} for row in rows),
                    'actions': [row['behavior'] for row in rows if row.get('behavior') in {
                        'hand_raised','writing','manipulating_materials','handing_materials','receiving_materials',
                        'head_toward_materials','head_toward_visible_person','head_toward_camera',
                        'head_away_from_materials','seated','standing','walking','out_of_seat'}],
                    'valid_box_fields': all(box is None or type(box) is int and 1 <= box <= 12
                        or isinstance(box,dict) and set(box)=={'x','y','width','height'} for box in boxes)})
        except Exception:
            report['structure_unreadable'] = True
        reports.append(report)
    print(json.dumps(reports),flush=True)


if __name__ == '__main__':
    main()
