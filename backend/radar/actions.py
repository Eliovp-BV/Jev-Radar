"""Editable, finite suggestions. These templates never execute external actions."""
from pydantic import Field
from .schemas import Strict
from .storage import fingerprint
from .evidence import current_findings
from .program import active_program

class ActionTemplate(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,40}$')
    title: str = Field(min_length=5,max_length=160)
    experiment: str = Field(min_length=10,max_length=800)
    success_measure: str = Field(min_length=5,max_length=500)
    lenses: list[str] = Field(default_factory=lambda:['all'],min_length=1,max_length=10)
    requires_gap: bool = False

DEFAULT_ACTIONS=[
 {'id':'resolve_gap','title':'Resolve the {criterion} evidence gap','experiment':'Inspect a primary source for each missing {criterion} answer, look for counterevidence, and record the scope and date.','success_measure':'Previously unknown comparison fields resolved with reviewable sources.','lenses':['all'],'requires_gap':True},
 {'id':'independent_check','title':'Independently check the {criterion} claims','experiment':'Choose one material {criterion} assertion and inspect an independent primary source or reproducible method. Record agreement, contradiction or remaining uncertainty.','success_measure':'One scoped claim independently checked; record the result even if it contradicts the initial source.','lenses':['all'],'requires_gap':False},
 {'id':'buyer_question','title':'Test a useful answer about {criterion}','experiment':'Draft a source-linked comparison answering the {criterion} question for the intended audience. Have representative readers complete a specific buying or evaluation task before deciding whether to publish.','success_measure':'Observed reader task completion and useful feedback; commercial lift remains unknown until measured.','lenses':['landscape','content'],'requires_gap':False},
 {'id':'distribution_test','title':'Test one evidenced distribution route','experiment':'Choose one public channel explicitly named in the collected distribution evidence. Plan a small owner-reviewed content experiment with an ordinary comparison artifact and a fixed observation window. No automatic posting.','success_measure':'Dated, source-linked engagement observations on the same platform and window; include low-performing artifacts.','lenses':['campaign'],'requires_gap':False}
]

def construct(store,mid,current=False):
    mission=store.mission(mid); entities=[e for e in store.records(mid,'entity') if e.get('review')!='rejected']; out=[]
    if not entities:return out
    eligible={f['id']:f for f in current_findings(store.records(mid,'finding')) if f.get('status') in ('supported','partly_supported')}
    library=store.setting('action_library',DEFAULT_ACTIONS)
    program=active_program(store,mid)
    criteria=program['criteria'] if program else mission['plan']['criteria']
    for criterion in criteria:
        known=[]
        for entity in entities:
            field=entity['fields'].get(criterion['id'],{})
            if field.get('stale'):continue
            candidates=[field.get('finding_id')]+list(reversed(field.get('other_findings',[])))
            fid=next((fid for fid in candidates if fid in eligible and eligible[fid].get('criterion_id')==criterion['id'] and eligible[fid].get('entity_id')==entity['id']),None)
            if fid:known.append((entity,fid))
        missing=len(entities)-len(known)
        for action in library:
            if 'all' not in action['lenses'] and mission['plan']['lens_id'] not in action['lenses']:continue
            if action['requires_gap'] and not missing:continue
            if not action['requires_gap'] and not known:continue
            def fill(text):return text.replace('{criterion}',criterion['label'].lower()).replace('{goal}',mission['goal'])
            out.append({'id':fingerprint({'mission':mid,'criterion':criterion['id'],'action':action['id']})[:32],
                        'template_id':action['id'],'title':fill(action['title']),'kind':'hypothesis / proposed experiment',
                        'relevance':f"Addresses the goal through: {criterion['question']}",
                        'evidence_ids':[fid for entity,fid in known],
                        'context_source_ids':list(dict.fromkeys(sid for e in entities for sid in e.get('source_ids',[])))[:6],
                        'uncertainty':f'{missing} of {len(entities)} inspected entities lack a current linked answer. Public assertions and content gaps do not establish demand, traffic or poor performance.',
                        'experiment':fill(action['experiment']),'success_measure':fill(action['success_measure'])})
    priorities=[p for p in store.records(mid,'opportunity_priority') if p.get('rubric_version')==mission['plan_version']]
    selected=priorities[-1].get('selected') if priorities and not current else None
    if priorities and not current and priorities[-1].get('suggestions'): out=priorities[-1]['suggestions']
    for opportunity in out:
        opportunity['jev_priority']=opportunity['id']==selected
        if opportunity['jev_priority']:opportunity['decision_id']=priorities[-1]['decision_id']
    return sorted(out,key=lambda o:not o['jev_priority'])
