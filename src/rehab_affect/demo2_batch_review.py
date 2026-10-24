"""Conservative cross-video reconciliation; never sum duplicate opportunities."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def group_records(records, namespace, decisions):
    buckets={}
    for r in records:
        batch=r.get('course_batch_id') or r.get('task_id') or r['lesson_id']
        key=(batch,r['lesson_date'],r['student_id'],r['goal_id'],r['measurement_context'],r['criterion'],r['rubric_version'])
        buckets.setdefault(key,[]).append(r)
    result=[]
    for key,values in sorted(buckets.items()):
        values=sorted(values,key=lambda r:r['record_id'])
        gid=digest([namespace,key])
        fingerprint=digest([[r['record_id'],r['version'],r.get('evidence_status','current'),r['reviewed'],r['assessment']['overall_score']] for r in values])
        decision=decisions.get(gid)
        valid=[r for r in values if r['reviewed'] and r.get('evidence_status','current')=='current']
        selected=None
        status='pending'
        if decision and decision['fingerprint']!=fingerprint:
            status='stale'
        elif len(values)==1 and not decision:
            selected=valid[0] if valid else None
            status='single' if selected else 'pending'
        elif decision and decision['fingerprint']==fingerprint:
            selected=next((r for r in valid if r['record_id']==decision['selected_record_id']),None)
            status='confirmed' if selected else 'stale'
        else:
            status='stale' if decision else 'needs_review'
        result.append({'group_id':gid,'fingerprint':fingerprint,'course_batch_id':key[0],
            'lesson_date':key[1],'student_id':key[2],'goal_id':key[3],'measurement_context':key[4],
            'criterion':key[5],'rubric_version':key[6],'records':values,'selected_record':selected,
            'status':status,'version':decision['version'] if decision else 0,
            'reason':decision['reason'] if decision else '',
            'score':selected['assessment']['overall_score'] if selected else None,
            'source_record_count':len(values)})
    return result


def trend_records(records, namespace, decisions):
    videos=[r for r in records if r['source_type']=='video_review']
    result=[r for r in records if r['source_type']!='video_review']
    for group in group_records(videos,namespace,decisions):
        if group['selected_record']:
            result.append(group['selected_record'])
        else:
            first=group['records'][0]
            result.append({**first,'record_id':'batch-'+group['group_id'], 'reviewed':False,
                'assessment':{**first['assessment'],'overall_score':None,'provisional_score':None,
                              'reviewed':False,'insufficient_evidence':True}})
    return result
