"""Observed primary-source leads; synthetic HTML, no network or inference."""
from radar.acquisition import extract
from radar.storage import now


def page(body):
    return extract({'url':'https://example.org/research','body':body.encode(),'status':200,'retrieved_at':now(),'headers':{}})


def test_content_references_survive_large_navigation_without_losing_navigation_fallback():
    nav=''.join(f'<a href="/navigation/{i}">Menu {i}</a>' for i in range(240))
    source=page(f'<nav>{nav}</nav><main><h1>Fixture lead list</h1><a href="https://www.youtube.com/watch?v=fixture001">Original example</a></main>')
    assert source['links'][0]['url']=='https://www.youtube.com/watch?v=fixture001'
    assert len(source['links'])==200
    assert any('/navigation/' in link['url'] for link in source['links'])


def test_observed_embedded_video_becomes_a_lead_but_never_media_evidence():
    source=page('<article><p>Fixture commentary only.</p><iframe title="Example clip" src="https://www.youtube-nocookie.com/embed/fixture001"></iframe><iframe src="http://127.0.0.1/hidden"></iframe><iframe src="https://example.net/widget"></iframe></article>')
    assert len(source['links'])==1
    lead=source['links'][0]
    assert lead['url']=='https://www.youtube.com/watch?v=fixture001'
    assert lead['observed_url']=='https://www.youtube-nocookie.com/embed/fixture001'
    assert lead['label']=='Example clip' and 'not inspected' in lead['provenance']
    assert not source.get('source_kind') and not source.get('video_metadata')
    assert source['text']=='Fixture commentary only.'


def test_original_video_footnotes_survive_hundreds_of_internal_article_links():
    internal=''.join(f'<a href="/article/{i}">Topic {i}</a>' for i in range(260))
    source=page(f'<main>{internal}<p>Reference</p><a href="https://youtu.be/fixture002">Original upload</a></main>')
    assert source['links'][0]['url']=='https://www.youtube.com/watch?v=fixture002'
    assert source['links'][0]['observed_url']=='https://youtu.be/fixture002'
    assert len(source['links'])==200
