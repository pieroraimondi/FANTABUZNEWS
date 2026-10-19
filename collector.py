"""Raccolta: RSS diretti + Google News RSS per team / testate locali.

Nessun bypass di login, paywall o API social; conserva titolo/estratto/link.
"""
import html
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from catalog import TEAMS, DIRECT_FEEDS, SPECIAL_SITES, host_of, classify_source, match_teams

class Stripper(HTMLParser):
    def __init__(self): super().__init__(); self.out=[]
    def handle_data(self, data): self.out.append(data)

def clean_markup(markup):
    p=Stripper()
    try: p.feed(html.unescape(markup or ''))
    except Exception: pass
    return re.sub(r'\s+', ' ', ''.join(p.out)).strip()

def feed_url(team, local=False, official=False):
    q=team.query
    if official:
        host=host_of(team.official)
        if not host: return None
        q+= ' site:'+host
    elif local:
        clauses=['site:'+x for x in team.local]
        if not clauses: return None
        q+=' ('+' OR '.join(clauses)+')'
    q+=' when:10d'
    return 'https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q,'hl':'it','gl':'IT','ceid':'IT:it'})


# Siti aggiunti nella V3: interrogazioni RSS Google News limitate al singolo dominio.
def specialist_feed_url(site):
    q='site:'+site['domain']
    if site.get('query'):
        q+=' '+site['query']
    q+=' when:10d'
    return 'https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q,'hl':'it','gl':'IT','ceid':'IT:it'})

class PublicTelegramParser(HTMLParser):
    """Lettura minimale dei messaggi *pubblici*, senza accesso/login/API privata.

    Telegram puo' cambiare HTML, login o regole: lettura non garantita.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]
        self.current=None
        self.root_depth=0
        self.items=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        classes=set(attrs.get('class','').split())
        self.stack.append((tag,classes))
        if tag=='div' and 'tgme_widget_message' in classes and attrs.get('data-post'):
            self.current={'post':attrs['data-post'], 'text':[], 'date':None}
            self.root_depth=len(self.stack)
        if self.current is not None and tag=='time' and attrs.get('datetime'):
            self.current['date']=attrs['datetime']
        if self.current is not None and tag in ('p','br','div') and 'tgme_widget_message_text' not in classes:
            # Conserva spazi tra elementi inline/div, senza alterare il contenuto semantico.
            if any('tgme_widget_message_text' in c for _,c in self.stack[:-1]):
                self.current['text'].append(' ')

    def handle_data(self, data):
        if self.current is not None and any('tgme_widget_message_text' in c for _,c in self.stack):
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if self.stack:
            # HTML pubblico di Telegram e' normalmente ben formato ma tolleriamo nesting imperfetto.
            pos=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
            if pos is not None: self.stack=self.stack[:pos]
        if self.current is not None and len(self.stack)<self.root_depth:
            self.items.append(self.current)
            self.current=None

def parse_public_telegram(page, channel='mondoaspicchicanale'):
    parser=PublicTelegramParser()
    parser.feed(page)
    result=[]
    for post in parser.items[:40]:
        text=re.sub(r'\s+',' ',''.join(post['text'])).strip()
        post_id=post['post'].rsplit('/',1)[-1]
        if not post_id.isdigit() or len(text)<12: continue
        result.append({'title':text[:260], 'summary':text[:450],
                       'url':'https://t.me/'+channel+'/'+post_id, 'source':'Mondo a Spicchi — Telegram',
                       'host':'t.me', 'published':_parse_date(post['date']),
                       'origin_hint':'social', 'hinted_team':None})
    return result

def fetch_public_telegram(url):
    req=urllib.request.Request(url,headers={
        'User-Agent':'Mozilla/5.0 (compatible; BasketNews/1.1; public channel reader)',
        'Accept':'text/html,application/xhtml+xml'})
    with urllib.request.urlopen(req,timeout=16) as response:
        if response.status!=200: raise ValueError('HTTP '+str(response.status))
        body=response.read(1_500_001)
    if len(body)>1_500_000: raise ValueError('pagina Telegram troppo grande')
    records=parse_public_telegram(body.decode('utf-8','replace'))
    if not records: raise ValueError('nessun messaggio pubblico leggibile (HTML cambiato o accesso limitato)')
    return records

def _parse_date(s):
    if not s: return None
    try:
        d=parsedate_to_datetime(s)
        return (d.replace(tzinfo=timezone.utc) if not d.tzinfo else d).astimezone(timezone.utc).isoformat(timespec='seconds')
    except Exception:
        try: return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc).isoformat(timespec='seconds')
        except Exception: return None

def _find(node, names):
    for name in names:
        v=node.findtext(name)
        if v: return v
    return ''

def get_xml(url):
    req=urllib.request.Request(url,headers={
        'User-Agent':'BasketNews/1.0 (+rassegna personale; RSS reader)',
        'Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9,*/*;q=0.7'
    })
    with urllib.request.urlopen(req,timeout=16) as response:
        if response.status != 200: raise ValueError('HTTP '+str(response.status))
        body=response.read(1_500_001)
    if len(body)>1_500_000: raise ValueError('feed troppo grande')
    return ET.fromstring(body)

def parse_feed(root, feed_meta):
    items=root.findall('.//item')
    if not items: items=root.findall('.//{http://www.w3.org/2005/Atom}entry')
    records=[]
    for item in items[:35]:
        title=clean_markup(_find(item,['title','{http://www.w3.org/2005/Atom}title']))
        link=_find(item,['link'])
        if not link:
            node=item.find('{http://www.w3.org/2005/Atom}link')
            if node is not None: link=node.get('href','')
        link=link.strip()
        if not title or not link.startswith(('https://','http://')): continue
        src_node=item.find('source')
        source_name=(src_node.text or '').strip() if src_node is not None else ''
        source_url=(src_node.get('url','') if src_node is not None else '')
        publisher_host=host_of(source_url) or host_of(link)
        summary=clean_markup(_find(item,['description','{http://www.w3.org/2005/Atom}summary','{http://purl.org/rss/1.0/modules/content/}encoded']))[:450]
        published=_parse_date(_find(item,['pubDate','{http://www.w3.org/2005/Atom}published','{http://www.w3.org/2005/Atom}updated','{http://purl.org/dc/elements/1.1/}date']))
        records.append({'title':title[:300],'url':link,'summary':summary,
                        'source':source_name or feed_meta['name'], 'host':publisher_host,
                        'published':published,'origin_hint':feed_meta.get('origin','altre'),
                        'hinted_team':feed_meta.get('team')})
    return records

KEYWORDS = {
    'Infortuni e assenze':r'\binfortun\w*|\bassenz\w*|\bindisponibil\w*|\bstop\b|\boperat\w*|\bfebbre\b|\bfermat\w*|\btrauma\b|\bdubbio\b|\bfuori (?:per|dai)\b|\binfermeria\b|\bnon giocher\w*|\binjury\b',
    'Mercato':r'\bmercato\b|\bfirm\w*|\bacquist\w*|\bingaggi\w*|\bcedut\w*|\brescission\w*|\bnuovo arrivo\b|\bcontratto\b|\btagliat\w*|\btrasferiment\w*',
    'Allenamenti':r'\ballenament\w*|\bpreparazion\w*|\bconvocat\w*|\brientr\w*|\bsedut[ae]\b',
    'Società':r'\bpresident\w*|\bsociet\w*|\bdirigen\w*|\bbilancio\b|\bsponsor\b|\bpropriet\w*|\bfideiussion\w*',
    'Dichiarazioni':r'\bintervista\b|\bdichiar\w*|\bparla\b|\bcoach\b|\bconferenza stamp\w*|\bcomment\w*',
    'Partite e risultati':r'\bpartit\w*|\bpost.partita\b|\bpre.partita\b|\bvittori\w*|\bsconfitt\w*|\brisultat\w*|\bpunteggi\w*|\bclassific\w*|\bquart\w*|\bfinale\b|\bvs\b',
}

def classify_topic(text):
    s=text.lower()
    for name,regex in KEYWORDS.items():
        if re.search(regex,s,re.IGNORECASE): return name
    return 'Altro'

def priority(topic, title):
    if topic=='Infortuni e assenze': return 3
    if topic=='Mercato': return 2
    if re.search(r'\besoner\w*|\bdimission\w*|\bbancarott\w*',title,re.I): return 3
    return 0

def get_jobs():
    jobs=[]
    for t in TEAMS:
        jobs.append({'name':'Google News — '+t.name,'url':feed_url(t),'team':t.id,'origin':'altre'})
        if t.local:
            jobs.append({'name':'Stampa locale — '+t.name,'url':feed_url(t,local=True),'team':t.id,'origin':'locale'})
        if t.official:
            jobs.append({'name':'Sito club — '+t.name,'url':feed_url(t,official=True),'team':t.id,'origin':'ufficiale'})
    jobs += DIRECT_FEEDS
    for s in SPECIAL_SITES:
        jobs.append({'name':s['name']+' — ricerca per sito', 'url':specialist_feed_url(s),
                     'origin':s['origin'], 'team':s.get('team'), 'trusted_team':s.get('team')})
    jobs.append({'name':'Mondo a Spicchi — Telegram pubblico',
                 'url':'https://t.me/s/mondoaspicchicanale', 'origin':'social', 'kind':'telegram_public'})
    return jobs

def fetch_job(job):
    if job.get('kind')=='telegram_public':
        return fetch_public_telegram(job['url'])
    root=get_xml(job['url'])
    return parse_feed(root,job)

def run_collector(save, report):
    jobs=get_jobs()
    total=len(jobs)
    report(total=total,done=0,imported=0,errors=[])
    seen=0
    # Pool ridotto per non sovraccaricare Google News; richieste individuali in sola lettura.
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(fetch_job,j):j for j in jobs}
        for fut in as_completed(futures):
            j=futures[fut]
            try:
                items=fut.result()
                for item in items:
                    team_ids=match_teams(item['title'],item['summary'],item['hinted_team'])
                    if j.get('trusted_team') and j['trusted_team'] not in team_ids:
                        team_ids.append(j['trusted_team'])
                    if not team_ids: continue
                    item['teams']=team_ids
                    origin=classify_source(item['host'],item['hinted_team'])
                    if j['origin']=='social': origin='social'
                    if origin=='altre' and j['origin']=='locale': origin='locale'
                    if origin=='altre' and j['origin']=='ufficiale': origin='ufficiale'
                    item['origin']=origin
                    item['category']=classify_topic(item['title']+' '+item['summary'])
                    item['priority']=priority(item['category'],item['title'])
                    save(item)
                    seen+=1
            except Exception as exc:
                report(error={'fonte':j['name'],'errore':str(exc)[:110]})
            report(progress=1, imported=seen)
    return seen
