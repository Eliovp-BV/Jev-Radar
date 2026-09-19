"""Video adapter fixtures only: no network, provider keys or media downloads."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from radar.acquisition import extract
from radar.search import Search, SearchError
from radar.video import canonical_video_url, enrich_video_source, is_video_url, source_from_result
from radar.video import enrich_youtube_source, MAX_PLAYER_LITERAL, MAX_YOUTUBE_HTML


VIDEO_URL='https://www.youtube.com/watch?v=fixture1234'
OBS={'id':'search-fixture','query':'example short videos','provider':'brave','language':'en','timestamp':'2026-09-19T12:00:00+00:00',
     'endpoint':'https://api.search.brave.com/res/v1/videos/search','latency_ms':12.34}
RESULT={'id':'result-fixture','url':VIDEO_URL,'title':'A surprising demonstration','snippet':'Watch this experiment unfold.',
        'position':3,'video':{'duration':'01:30','views':1234,'creator':'Fixture creator','publisher':'YouTube'},
        'page_age':'2026-09-01T12:00:00Z','page_fetched':'2026-09-18T11:00:00Z'}
ACTION={'id':'action-fixture','kind':'video','value':VIDEO_URL,'depth':0}


@pytest.mark.parametrize('url',[VIDEO_URL,'https://youtu.be/fixture1234?t=2','https://www.youtube.com/shorts/fixture1234','https://www.youtube-nocookie.com/embed/fixture1234'])
def test_one_video_has_one_identity_across_player_and_share_urls(url):
    assert is_video_url(url)
    assert canonical_video_url(url)==VIDEO_URL


@pytest.mark.parametrize('url',['https://www.youtube.com/results?search_query=viral','https://www.youtube.com/@creator','https://www.tiktok.com/@creator',
                               'https://blog.example/why-videos-went-viral','https://www.youtube.com.evil.example/watch?v=fixture1234','http://127.0.0.1/watch?v=fixture1234'])
def test_articles_and_platform_listings_are_not_individual_videos(url):
    assert not is_video_url(url)


def test_index_record_has_exact_evidence_and_no_unearned_media_claims():
    source=source_from_result(RESULT,OBS,ACTION)
    assert source['source_kind']=='video' and source['unit_id']==VIDEO_URL
    assert source['retrieved_at']==OBS['timestamp'] and source['fetch_ms']==0 and source['status_code'] is None
    assert source['video_metadata']['views']==1234 and source['video_metadata']['transcript'] is None
    assert not source['video_metadata']['transcript_available'] and not source['video_metadata']['frames_available']
    assert source['video_metadata']['acquisition']=='search_provider_metadata'
    assert 'not fetched or watched' in source['coverage']['method']
    assert source['provider_observation']['latency_ms']==12.34 and source['provider_observation']['search_id']==OBS['id']
    assert all(source['text'][chunk['start']:chunk['end']]==chunk['text'] for chunk in source['chunks'])
    assert all('results[]' in chunk['provenance'] for chunk in source['chunks'])
    assert 'page date' in source['source_date_provenance']


@pytest.mark.parametrize('views',[None,'1.2M','1234',True,-1,1.4])
def test_index_counter_is_numeric_only_without_popularity_estimates(views):
    result=deepcopy(RESULT);result['video']['views']=views
    source=source_from_result(result,OBS,ACTION)
    assert source['video_metadata']['views'] is None
    assert not any(chunk['field']=='views' for chunk in source['chunks'])
    assert source['native_video_metadata']['views']==views


def test_distinct_videos_with_same_description_do_not_deduplicate():
    first=source_from_result(RESULT,OBS,ACTION)
    second=source_from_result({**RESULT,'url':'https://www.youtube.com/watch?v=another1234'},OBS,ACTION)
    assert first['unit_id']!=second['unit_id'] and first['content_hash']!=second['content_hash']


def page_source(structured,url=VIDEO_URL):
    import json
    html='<html><title>Video page</title><script type="application/ld+json">'+json.dumps(structured)+'</script><main><p>Original visible text.</p></main></html>'
    return extract({'body':html,'url':url,'retrieved_at':OBS['timestamp'],'status':200,'fetch_ms':3.1})


def test_fetched_video_transcript_is_exact_and_publisher_provenance_is_retained():
    transcript='The opening question is: can this work?\nThen we reveal the result. '*20
    source=page_source({'@type':'VideoObject','url':VIDEO_URL,'name':'Experiment','description':'A public description.',
                        'transcript':transcript,'duration':'PT90S','uploadDate':'2026-09-01',
                        'interactionStatistic':{'@type':'InteractionCounter','interactionType':'https://schema.org/WatchAction','userInteractionCount':'4000'}})
    previous=deepcopy(source);result=enrich_video_source(source)
    assert source==previous
    assert result['text'].startswith(previous['text']) and result['chunks'][:len(previous['chunks'])]==previous['chunks']
    assert result['video_metadata']['transcript']==transcript and result['video_metadata']['transcript_available']
    assert result['video_metadata']['views']==4000 and result['video_metadata']['acquisition']=='publisher_structured_metadata'
    assert result['fetch_ms']==3.1 and not result['video_metadata']['frames_available']
    assert all(result['text'][chunk['start']:chunk['end']]==chunk['text'] for chunk in result['chunks'])
    transcript_chunks=[chunk for chunk in result['chunks'] if chunk.get('field')=='transcript']
    assert ''.join(chunk['text'] for chunk in transcript_chunks)==transcript
    assert all('.transcript' in chunk['provenance'] for chunk in transcript_chunks)


def test_embedded_unrelated_video_cannot_turn_article_into_video_evidence():
    source=page_source({'@type':'VideoObject','url':VIDEO_URL,'name':'Embedded video'},'https://blog.example/viral-analysis')
    assert enrich_video_source(source)==source


def test_ambiguous_video_objects_are_not_arbitrarily_selected():
    source=page_source([{'@type':'VideoObject','url':VIDEO_URL,'name':'First record'},
                        {'@type':'VideoObject','url':VIDEO_URL,'name':'Conflicting record'}])
    assert enrich_video_source(source)==source


def test_distinct_counter_windows_are_not_combined_as_current_views():
    counters=[{'interactionType':'WatchAction','userInteractionCount':4,'startTime':'2026-01-01'},
              {'interactionType':'WatchAction','userInteractionCount':8,'startTime':'2026-02-01'}]
    source=page_source({'@type':'VideoObject','url':VIDEO_URL,'interactionStatistic':counters})
    assert enrich_video_source(source)['video_metadata']['views'] is None


async def call_search(response):
    settings=SimpleNamespace(brave_key='fixture-key-not-live',user_agent='fixture')
    client=AsyncMock();client.__aenter__.return_value=client;client.get.return_value=response
    with patch('radar.search.httpx.AsyncClient',return_value=client):
        result=await Search(settings).videos('example videos','France','en-US')
    return result,client


async def test_brave_adapter_uses_video_endpoint_bounded_results_and_raw_counts():
    response=httpx.Response(200,json={'results':[{'url':VIDEO_URL,'title':'<b>Experiment</b>','description':'<b>Original</b> text',
                                               'video':{'views':1234,'duration':'01:30'}},
                                              {'url':'https://blog.example/viral-video-list','title':'Article'}]})
    observation,client=await call_search(response)
    args=client.get.call_args
    assert args.args[0]=='https://api.search.brave.com/res/v1/videos/search'
    assert args.kwargs['params']=={'q':'example videos','count':8,'search_lang':'en','country':'ALL'}
    assert len(observation['results'])==1 and observation['skipped_results']==1
    assert observation['results'][0]['video']['views']==1234
    assert observation['results'][0]['snippet']=='Original text' and observation['results'][0]['title']=='Experiment'
    assert observation['latency_ms']>=0 and observation['timestamp'] and observation['estimated_usd'] is None
    assert observation['search_kind']=='video' and client.get.await_count==1
    assert 'fixture-key' not in str(observation)


@pytest.mark.parametrize('status',[401,429,503])
async def test_video_provider_error_never_retries_or_falls_back_to_articles(status):
    response=httpx.Response(status,json={'error':{'detail':'potentially sensitive provider body'}})
    client=AsyncMock();client.__aenter__.return_value=client;client.get.return_value=response
    with patch('radar.search.httpx.AsyncClient',return_value=client):
        with pytest.raises(SearchError,match=f'HTTP {status}; provider stopped, no retries'):
            await Search(SimpleNamespace(brave_key='fixture-only',user_agent='fixture')).videos('videos','FR','en')
    assert client.get.await_count==1


async def test_video_provider_malformed_body_is_an_error_not_empty_success():
    with pytest.raises(SearchError,match='valid result list'):
        await call_search(httpx.Response(200,json={'unexpected':[]}))


def youtube_page(player,assignment='var ytInitialPlayerResponse = ',suffix=';',url=VIDEO_URL):
    import json
    literal=json.dumps(player) if isinstance(player,dict) else player
    body=('<html><title>YouTube</title><script>'+assignment+literal+suffix+'</script><body><p>Footer text.</p></body></html>').encode()
    raw={'url':url,'body':body,'retrieved_at':OBS['timestamp'],'status':200,'fetch_ms':7.5}
    return raw,extract(raw)


def test_permitted_youtube_literal_retains_primary_metadata_exact_offsets_without_player_secrets():
    player={'videoDetails':{'videoId':'fixture1234','title':'A real experiment?','author':'Publisher fixture',
                            'shortDescription':'The publisher describes an experiment.\nThe result is documented in these words.',
                            'viewCount':'0001234','lengthSeconds':'90','channelId':'not-needed'},
            'microformat':{'playerMicroformatRenderer':{'uploadDate':'2026-09-01','publishDate':'2026-09-02'}},
            'streamingData':{'formats':[{'url':'https://private.example/media?token=PLAYER_PRIVATE_MARKER'}]},
            'captions':{'playerCaptionsTracklistRenderer':{'captionTracks':[{'baseUrl':'https://private.example/caption?token=CAPTION_PRIVATE_MARKER'}]}}}
    raw,source=youtube_page(player);before=deepcopy(source)
    result=enrich_youtube_source(raw,source,requested_url='https://youtu.be/fixture1234')
    metadata=result['video_metadata']
    assert source==before and result['source_kind']=='video' and result['unit_id']==VIDEO_URL
    assert metadata['title']=='A real experiment?' and metadata['creator']=='Publisher fixture'
    assert metadata['views']==1234 and metadata['duration']=='90 seconds' and metadata['duration_seconds']==90
    assert metadata['published_at']=='2026-09-01' and 'uploadDate' in metadata['published_at_basis']
    assert metadata['acquisition']=='publisher_player_metadata' and metadata['provider']=='youtube.com'
    assert metadata['transcript'] is None and not metadata['transcript_available'] and not metadata['frames_available']
    assert result['fetch_ms']==7.5 and result['retrieved_at']==OBS['timestamp']
    assert result['coverage']['video_metadata_status']=='matched_publisher_metadata'
    assert result['text'].startswith(before['text']) and result['extraction_ms']>=before['extraction_ms']
    assert all(result['text'][chunk['start']:chunk['end']]==chunk['text'] for chunk in result['chunks'])
    views=next(chunk for chunk in result['chunks'] if chunk.get('field')=='views')
    assert views['text']=='0001234' and 'ytInitialPlayerResponse.videoDetails.viewCount' in views['provenance']
    assert 'PLAYER_PRIVATE_MARKER' not in str(result) and 'CAPTION_PRIVATE_MARKER' not in str(result)


@pytest.mark.parametrize('assignment',["window['ytInitialPlayerResponse'] = ",'window["ytInitialPlayerResponse"] = ','window.ytInitialPlayerResponse = '])
def test_youtube_literal_window_assignments_are_supported(assignment):
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'A public title'}},assignment=assignment)
    assert enrich_youtube_source(raw,source)['video_metadata']['title']=='A public title'


def test_youtube_literal_requires_original_requested_video_identity():
    raw,source=youtube_page({'videoDetails':{'videoId':'other1234','title':'Wrong video'}})
    result=enrich_youtube_source(raw,source)
    assert result['coverage']['video_metadata_status']=='identity_mismatch' and 'source_kind' not in result
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Redirected video'}})
    result=enrich_youtube_source(raw,source,requested_url='https://www.youtube.com/watch?v=other1234')
    assert result['coverage']['video_metadata_status']=='identity_mismatch' and 'source_kind' not in result


@pytest.mark.parametrize('literal,suffix',[("JSON.parse('someValue')",';'),('buildPlayerData()', ';'),('{"videoDetails":',';'),
                                          ('{"videoDetails":{"videoId":"fixture1234","title":"Not a literal assignment"}}',' || replacePlayer();')])
def test_youtube_does_not_evaluate_javascript_or_accept_malformed_json(literal,suffix):
    raw,source=youtube_page(literal,suffix=suffix)
    result=enrich_youtube_source(raw,source)
    assert 'source_kind' not in result and result['text']==source['text']
    assert result['coverage']['video_metadata_status'] in ('unavailable','malformed','nonliteral')


def test_youtube_player_and_html_size_bounds_are_enforced():
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Oversized'},'noise':'x'*MAX_PLAYER_LITERAL})
    assert enrich_youtube_source(raw,source)['coverage']['video_metadata_status']=='oversized'
    raw['body']=b'x'*(MAX_YOUTUBE_HTML+1)
    assert enrich_youtube_source(raw,source)['coverage']['video_metadata_status']=='oversized'


def test_youtube_description_is_bounded_and_invalid_counters_and_dates_stay_unknown():
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Title','shortDescription':'a'*13000,
                                           'viewCount':'1.2M','lengthSeconds':True},
                            'microformat':{'playerMicroformatRenderer':{'uploadDate':'not-a-date'}}})
    result=enrich_youtube_source(raw,source);metadata=result['video_metadata']
    assert len(metadata['description'])==12000 and result['coverage']['truncated']
    assert result['coverage']['video_truncated_fields']==['description']
    assert metadata['views'] is None and metadata['duration'] is None and metadata['published_at'] is None
    assert ''.join(c['text'] for c in result['chunks'] if c.get('field')=='description')==metadata['description']
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Malformed counters',
                                           'viewCount':'9'*5000,'lengthSeconds':'²'}})
    metadata=enrich_youtube_source(raw,source)['video_metadata']
    assert metadata['views'] is None and metadata['duration'] is None


def test_youtube_parser_ignores_non_youtube_pages_and_conflicting_literals():
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Embedded'}},url='https://article.example/story')
    assert enrich_youtube_source(raw,source)==source
    raw,source=youtube_page('{"videoDetails":{"videoId":"fixture1234","title":"First"}};\nvar ytInitialPlayerResponse={"videoDetails":{"videoId":"fixture1234","title":"Second"}}')
    result=enrich_youtube_source(raw,source)
    assert result['coverage']['video_metadata_status']=='ambiguous' and 'source_kind' not in result


def test_youtube_description_exposes_only_observed_public_video_links_with_exact_offsets():
    description=('A permitted original: https://youtu.be/original001. '
                 'Rejected network target: http://127.0.0.1/watch?v=private001 '
                 'Unrelated article: https://article.example/viral-list '
                 'Unsafe parameter: https://www.youtube.com/watch?v=secret001&token=private '
                 'No self-loop: https://youtu.be/fixture1234 ')
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Links as leads','shortDescription':description},
                            'streamingData':{'url':'https://youtu.be/stream001'}})
    result=enrich_youtube_source(raw,source)
    links=[link for link in result['links'] if link.get('provenance','').startswith('ytInitialPlayerResponse')]
    assert len(links)==1 and links[0]['url']=='https://youtu.be/original001'
    assert result['text'][links[0]['start']:links[0]['end']]=='https://youtu.be/original001'
    assert result['coverage']['uninspected_links']==len(result['links'])


def test_youtube_description_video_leads_are_bounded_to_eight_unique_observed_urls():
    description=' '.join('https://youtu.be/fixtureLead'+str(index) for index in range(12))
    raw,source=youtube_page({'videoDetails':{'videoId':'fixture1234','title':'Many leads','shortDescription':description}})
    result=enrich_youtube_source(raw,source)
    links=[link for link in result['links'] if link.get('provenance','').startswith('ytInitialPlayerResponse')]
    assert len(links)==8 and all(link['url'] in description for link in links)
