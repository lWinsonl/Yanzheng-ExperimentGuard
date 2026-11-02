"""Run the frozen public-material pilot, with explicit opt-in to eight bounded provider calls.

Prepare inputs first; see docs/evaluation/real-case-pilot-protocol.md. This runner
never reads the gold file, changes application code, or accesses production data.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def application_sha256():
    digest=hashlib.sha256()
    for path in sorted((ROOT/'backend/app').rglob('*.py')):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    out=args.input_dir.resolve()
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    encoded=(out/'inputs.json').read_bytes()
    assert hashlib.sha256(encoded).hexdigest()==manifest['inputs_sha256'],'Input changed after freeze'
    protocol=ROOT/manifest.get('protocol_file','docs/evaluation/real-case-pilot-protocol.md')
    assert hashlib.sha256(protocol.read_bytes()).hexdigest()==manifest['protocol_sha256'],'Protocol changed after freeze'
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert commit==manifest['source_commit'],'Application commit changed after freeze'
    if manifest.get('application_sha256'):
        assert application_sha256()==manifest['application_sha256'],'Frozen application changed'
    else:
        assert not subprocess.check_output(['git','diff','HEAD','--','backend/app'],cwd=ROOT),'Application has uncommitted changes'
    cases=json.loads(encoded)['cases']
    if args.live and (out/'live-results.json').exists():
        raise SystemExit('Refusing to overwrite or selectively rerun an existing live run')
    if not args.live:
        os.environ.update(LLM_API_KEY='',LLM_BASE_URL='',LLM_MODEL='')
    with tempfile.TemporaryDirectory(prefix='yanzheng-real-pilot-') as temporary:
        os.environ['DATA_DIR']=str(Path(temporary)/'sessions')
        os.chdir(ROOT/'backend')
        sys.path.insert(0,str(ROOT/'backend'))
        from app.config import settings
        from app.agent.llm_client import llm_client
        from app.agent.agent_service import agent_service
        from app.agent import prompts
        from app.services import evidence_chain,review_service,claim_graph_service,data_store
        sessions={}
        rules=[]
        facts=[]
        with patch.object(llm_client,'is_available',return_value=False):
            for case in cases:
                session=evidence_chain.create_session('Public pilot '+case['case_id'],'data_model',[case['claim']])
                sid=session.session_id
                for material in case['materials']:
                    assert hashlib.sha256(material['content'].encode()).hexdigest()==material['sha256']
                    evidence_chain.extract_from_text(sid,material['content'],material['filename'],material['role'])
                store=data_store.require(sid)
                for fact in store.facts.values():
                    assert fact.source.verify(store.docs[fact.source.material_id])
                    evidence_chain.confirm_fact(sid,fact.fact_id,'confirm')
                report=review_service.run_review(sid)
                graph=claim_graph_service.build_graph(sid)
                rules.append({'case_id':case['case_id'],'report':report.model_dump(mode='json'),'graph':graph.model_dump(mode='json')})
                facts.append({'case_id':case['case_id'],'facts':[f.model_dump(mode='json') for f in store.facts.values()]})
                sessions[case['case_id']]=sid
        dump(out/('rules-live-context.json' if args.live else 'rules-results.json'),rules)
        if not args.live:
            dump(out/'facts-for-review.json',facts)
            print(json.dumps({'stage':'rules','cases':len(rules),'facts':[{'case_id':x['case_id'],'count':len(x['facts'])} for x in facts]},ensure_ascii=True),flush=True)
            return 0
        if not llm_client.is_available():
            raise SystemExit('Configured live model unavailable; offline results retained')
        calls=[]
        state={'case_id':'','condition':'','stop':False}
        real_open=urllib.request.urlopen
        real_chat=llm_client.chat
        endpoint=settings.llm_base_url.rstrip('/')+'/chat/completions'

        def capture_open(request,*a,**kw):
            if request.full_url!=endpoint:
                raise RuntimeError('Unexpected network destination in pilot')
            if len(calls)>=manifest['provider_attempt_cap']:
                raise RuntimeError('Pilot provider cap reached')
            row={'attempt':len(calls)+1,'case_id':state['case_id'],'condition':state['condition'],
                 'started_at_utc':datetime.now(timezone.utc).isoformat(),
                 'request':json.loads(request.data),'status':'started'}
            calls.append(row)
            dump(out/'provider-calls.json',calls)
            start=time.perf_counter()
            try:
                with real_open(request,*a,**kw) as response:
                    raw=response.read(3_000_001)
                    if len(raw)>3_000_000:raise ValueError('Provider response too large')
                    data=json.loads(raw)
                    row.update(status='ok',usage=data.get('usage',{}),returned_model=data.get('model'),
                               response=data['choices'][0]['message'].get('content'),finish_reason=data['choices'][0].get('finish_reason'))
                return io.BytesIO(raw)
            except Exception as exc:
                row.update(status='error',error_type=type(exc).__name__,http_status=getattr(exc,'code',None))
                if isinstance(exc,urllib.error.HTTPError) and exc.code in (401,403,429):state['stop']=True
                raise
            finally:
                row['duration_seconds']=round(time.perf_counter()-start,3)
                dump(out/'provider-calls.json',calls)

        def limited_chat(system_prompt,user_prompt,temperature=.2,max_tokens=2000,timeout=20,retries=0):
            return real_chat(system_prompt,user_prompt,temperature=temperature,
                             max_tokens=min(max_tokens,3000),timeout=min(timeout,45),retries=0)

        results=[]
        started=datetime.now(timezone.utc).isoformat()
        plan=[(case,'agent') for case in cases]+[(case,'direct_reference') for case in cases if case['case_id'] in manifest['baseline_case_ids']]
        with patch.object(urllib.request,'urlopen',side_effect=capture_open),patch.object(llm_client,'chat',side_effect=limited_chat):
            for case,condition in plan:
                state.update(case_id=case['case_id'],condition=condition)
                row={'case_id':case['case_id'],'condition':condition}
                if state['stop']:
                    row.update(status='not_run_after_provider_error')
                    results.append(row)
                    continue
                print(json.dumps({'stage':'live_start','case_id':case['case_id'],'condition':condition},ensure_ascii=True),flush=True)
                start=time.perf_counter()
                try:
                    sid=sessions[case['case_id']]
                    if condition=='agent':
                        result=agent_service.deep_review(sid)
                        row.update(asdict(result))
                    else:
                        store=data_store.require(sid)
                        materials,coverage=agent_service._materials_text(store,max_chars=8000)
                        raw=llm_client.chat(prompts.DEEP_REVIEW_SYSTEM,prompts.DEEP_REVIEW_USER.format(
                            claims='\n'.join('- '+c.text for c in store.session.claims),materials_text=materials,existing_findings='(无)'),
                            max_tokens=3000,timeout=45,retries=0)
                        data=llm_client.parse_json_response(raw)
                        if not isinstance(data,dict) or not isinstance(data.get('deep_findings'),list):
                            row.update(status='llm_parse_failed' if raw else 'llm_call_failed',findings=[])
                        else:
                            findings=agent_service._parse_deep_findings(store,data['deep_findings'])
                            row.update(status='ok' if findings else 'ok_no_findings',findings=[asdict(f) for f in findings])
                        row['coverage']=[asdict(c) for c in coverage]
                except Exception as exc:
                    row.update(status='application_error',error_type=type(exc).__name__)
                row['duration_seconds']=round(time.perf_counter()-start,3)
                # Independently check that a verified quote was actually visible to the model.
                store=data_store.require(sessions[case['case_id']])
                if row.get('evidence_catalog'):
                    catalog={e['evidence_id']:e for e in row['evidence_catalog']}
                    for finding in row.get('findings',[]):
                        refs=[catalog.get(eid) for eid in finding.get('evidence_ids',[])]
                        finding['ids_in_current_catalog']=bool(refs and all(refs))
                        finding['source_ranges_verified']=bool(refs and all(e and (
                            e['source_kind']=='program_result' or store.docs[e['material_id']].content[e['start_char']:e['end_char']]==e['text']) for e in refs))
                else:
                    _text,coverage=agent_service._materials_text(store,max_chars=8000)
                    sent={c.filename:store.docs[c.material_id].content[:c.checked_chars] for c in coverage}
                    for finding in row.get('findings',[]):
                        finding['quote_in_checked_range']=bool(finding.get('verified_quote') and finding['verified_quote'] in sent.get(finding.get('material_filename'),''))
                results.append(row)
                dump(out/'live-results.json',{'started_at_utc':started,'model':settings.llm_model,'source_commit':commit,'inputs_sha256':manifest['inputs_sha256'],'results':results,'provider_attempts':len(calls)})
                print(json.dumps({'stage':'live_done','case_id':case['case_id'],'condition':condition,'status':row['status'],'findings':len(row.get('findings',[])),'seconds':row['duration_seconds']},ensure_ascii=True),flush=True)
        dump(out/'live-results.json',{'started_at_utc':started,'model':settings.llm_model,'source_commit':commit,'inputs_sha256':manifest['inputs_sha256'],'results':results,'provider_attempts':len(calls)})
        print(json.dumps({'stage':'complete','attempts':len(calls),'statuses':[{'case_id':r['case_id'],'condition':r['condition'],'status':r['status']} for r in results]},ensure_ascii=True),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
