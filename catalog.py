"""Catalogo editabile. Le fonti Google News non garantiscono indicizzazione esaustiva."""

from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import re

@dataclass(frozen=True)
class Team:
    id: str
    name: str
    league: str
    query: str
    aliases: tuple
    official: str = ""
    local: tuple = ()

    def to_dict(self):
        return asdict(self)

# Locali: domini di quotidiani/testate territoriali, NON tutti garantiscono un feed RSS.
# Official: siti club; vuoto significa link non ancora verificato; LBA/LNP rimangono fonti ufficiali.
TEAMS = [
    Team('lba-udine','APU Udine','LBA','"APU Udine" basket',('apu udine','apudine','apu old wild west'), 'https://www.apubasket.it/',('messaggeroveneto.gelocal.it','udinetoday.it','megabasket.it')),
    Team('lba-trento','Aquila Basket Trento','LBA','"Dolomiti Energia Trentino" basket',('aquila basket','dolomiti energia trentino','dolomiti energia tn'),'https://www.aquilabasket.it/',('ladige.it','iltquotidiano.it')),
    Team('lba-bc-roma','BC Roma','LBA','"BC Roma" basket',('bc roma','basket club roma'),'https://www.officialbcroma.com/',('romatoday.it','ilmessaggero.it')),
    Team('lba-tortona','Derthona Tortona','LBA','"Bertram Derthona" basket',('derthona','bertram tortona','bertram derthona'),'https://www.derthonabasket.it/',('ilpiccolo.net','lastampa.it')),
    Team('lba-maxima','Maxima Roma','LBA','"Maxima Roma" basket',('maxima roma',),'',('romatoday.it','ilmessaggero.it')),
    Team('lba-napoli','Napoli Basketball','LBA','"Napoli Basketball"',('napoli basketball','guerri napoli'),'https://www.napolibasketball.com/',('ilmattino.it','napolitoday.it')),
    Team('lba-milano','Olimpia Milano','LBA','"Olimpia Milano" basket',('olimpia milano','armani milano','ea7 milano'),'https://www.olimpiamilano.com/',('milanotoday.it','ilgiorno.it')),
    Team('lba-cantu','Pallacanestro Cantù','LBA','"Acqua San Bernardo Cantù" basket',('pallacanestro cantù','pallacanestro cantu','acqua s.bernardo cantù','acqua san bernardo cantù'),'https://pallacanestrocantu.com/',('laprovinciadicomo.it','ilnotiziario.net')),
    Team('lba-trieste','Pallacanestro Trieste','LBA','"Pallacanestro Trieste"',('pallacanestro trieste',),'https://www.pallacanestrotrieste.it/',('ilpiccolo.it','megabasket.it','triesteprima.it')),
    Team('lba-varese','Pallacanestro Varese','LBA','"Openjobmetis Varese" basket',('pallacanestro varese','openjobmetis varese'),'https://www.pallacanestrovarese.it/',('varesenews.it','prealpina.it')),
    Team('lba-venezia','Reyer Venezia','LBA','"Reyer Venezia" basket',('reyer venezia','umana reyer venezia'),'https://www.reyer.it/',('nuovavenezia.gelocal.it','veneziatoday.it')),
    Team('lba-scafati','Scafati Basket','LBA','"Scafati Basket"',('scafati basket','longobardi scafati'),'https://www.scafatibasket.it/',('salernotoday.it','lacittadisalerno.it')),
    Team('lba-verona','Scaligera Verona','LBA','"Tezenis Verona" basket',('tezenis verona','scaligera basket','scaligera verona'),'https://www.scaligerabasket.it/',('larena.it','veronasera.it')),
    Team('lba-reggio','Pallacanestro Reggiana','LBA','"UNA Hotels Reggio Emilia" basket',('pallacanestro reggiana','una hotels reggio emilia','una hotels re'),'https://www.pallacanestroreggiana.it/',('gazzettadireggio.gelocal.it','ilrestodelcarlino.it')),
    Team('lba-treviso','Treviso Basket','LBA','"Nutribullet Treviso Basket"',('treviso basket','nutribullet treviso'),'https://www.trevisobasket.it/',('tribunatreviso.gelocal.it','trevisotoday.it')),
    Team('lba-virtus','Virtus Bologna','LBA','"Virtus Bologna" basket',('virtus bologna','virtus costa bologna','virtus olidata bologna'),'https://www.virtus.it/',('bolognabasket.org','ilrestodelcarlino.it')),
    Team('a2-avellino','Avellino Basket','A2','"Avellino Basket" A2',('avellino basket','halley campania avellino'),'https://www.avellinobasket.it/',('ottopagine.it','ilmattino.it')),
    Team('a2-fortitudo','Fortitudo Bologna','A2','"Fortitudo Bologna" basket',('fortitudo bologna','flats service fortitudo','fortitudo pallacanestro'),'https://fortitudobologna.it/',('bolognabasket.org','ilrestodelcarlino.it')),
    Team('a2-brindisi','Brindisi','A2','"Valtur Brindisi" basket',('new basket brindisi','valtur brindisi'),'https://www.newbasketbrindisi.it/',('brindisireport.it','quotidianodipuglia.it')),
    Team('a2-caserta','JuveCaserta','A2','"JuveCaserta" basket',('juvecaserta','juve caserta','provalue juvecaserta'),'https://www.juvecaserta.it/',('casertanews.it','ilmattino.it')),
    Team('a2-cento','Cento','A2','"Sella Cento" basket',('sella cento','benedetto xiv cento'),'https://www.benedettoxiv.it/',('ilrestodelcarlino.it','estense.com')),
    Team('a2-cividale','Cividale','A2','"Gesteco Cividale" basket',('gesteco cividale','ueb cividale','cividale basket'),'https://www.uebcividale.it/',('messaggeroveneto.gelocal.it','megabasket.it')),
    Team('a2-cremona','JuVi Cremona','A2','"Juvi Cremona" basket',('juvi cremona','ferraroni juvi'),'https://www.juvicremona.it/',('laprovinciacr.it','cremonaoggi.it')),
    Team('a2-forli','Forlì','A2','"Unieuro Forlì" basket',('unieuro forli','unieuro forlì','pallacanestro forlì'),'https://www.pallacanestroforli2015.it/',('forlitoday.it','ilrestodelcarlino.it')),
    Team('a2-livorno','Libertas Livorno','A2','"Libertas Livorno" basket',('libertas livorno','libertas livorno 1947'),'https://www.libertaslivorno1947.it/',('iltirreno.it','livornotoday.it')),
    Team('a2-mestre','Mestre','A2','"Gemini Mestre" basket',('gemini mestre','basket mestre'),'https://www.basketmestre.it/',('veneziatoday.it','nuovavenezia.gelocal.it')),
    Team('a2-urania','Urania Milano','A2','"Urania Milano" basket',('urania milano','weegreenit urania'),'https://www.uraniabasket.it/',('milanotoday.it','ilgiorno.it')),
    Team('a2-montecatini','Gema Montecatini','A2','"Gema Montecatini" basket',('gema montecatini','la t tecnica gema'),'https://www.gemamontecatini.it/',('iltirreno.it','lanazione.it')),
    Team('a2-pesaro','VL Pesaro','A2','"VL Pesaro" basket',('vl pesaro','victoria libertas pesaro','cmt orange tools pesaro'),'https://www.victorialibertas.it/',('ilrestodelcarlino.it','corriereadriatico.it')),
    Team('a2-pistoia','Pistoia Basket','A2','"Pistoia Basket"',('pistoia basket','lumos pistoia'),'https://www.pistoiabasket2000.com/',('lanazione.it','iltirreno.it')),
    Team('a2-rieti','Sebastiani Rieti','A2','"Sebastiani Rieti" basket',('sebastiani rieti','rsr sebastiani'),'https://www.sebastianibasket.it/',('ilmessaggero.it','rietilife.com')),
    Team('a2-rimini','Rimini','A2','"Dole Basket Rimini"',('dole basket rimini','rbr rimini','rinascita basket rimini'),'https://www.rinascitabasketrimini.it/',('ilrestodelcarlino.it','riminitoday.it')),
    Team('a2-ruvo','Ruvo di Puglia','A2','"Ruvo di Puglia" basket',('ruvo di puglia','crifo wines ruvo'),'https://www.pallacanestroruvodipuglia.it/',('baritoday.it','lagazzettadelmezzogiorno.it')),
    Team('a2-sassari','Dinamo Sassari','A2','"Dinamo Sassari" basket',('dinamo sassari','banco di sardegna sassari'),'https://www.dinamobasket.com/',('lanuovasardegna.it','unionesarda.it')),
    Team('a2-torino','Torino','A2','"Reale Mutua Torino" basket',('reale mutua torino','basket torino'),'https://www.basket-torino.it/',('torinotoday.it','lastampa.it')),
    Team('a2-vigevano','Vigevano','A2','"Elachem Vigevano" basket',('elachem vigevano','pallacanestro vigevano'),'https://www.pallacanestrovigevano.com/',('laprovinciapavese.gelocal.it','ilgiorno.it')),
]


# Integrazioni deliberate nella revisione V3 del 19/10/2026.
# Si tratta di domini per interrogazioni Google News, non di RSS diretti verificati.
from dataclasses import replace
EXTRA_LOCAL_DOMAINS = {'lba-tortona': ('radiogold.it',), 'lba-milano': ('realolimpiamilano.com',), 'lba-varese': ('varesenoi.it',), 'lba-venezia': ('ilgazzettino.it',), 'lba-reggio': ('reggionline.com',), 'lba-treviso': ('ilgazzettino.it',), 'lba-virtus': ('corrieredibologna.corriere.it',), 'a2-avellino': ('orticalab.it',), 'a2-fortitudo': ('corrieredibologna.corriere.it',), 'a2-forli': ('corriereromagna.it',), 'a2-livorno': ('amaranta.it',), 'a2-montecatini': ('pistoiasport.com',), 'a2-pistoia': ('pistoiasport.com',), 'a2-rimini': ('corriereromagna.it',), 'a2-ruvo': ('ruvolive.it',), 'a2-sassari': ('centotrentuno.com',), 'a2-vigevano': ('informatorevigevanese.it',)}
TEAMS = [replace(t, local=tuple(dict.fromkeys((*t.local, *EXTRA_LOCAL_DOMAINS.get(t.id, ()))))) for t in TEAMS]

# Fonti editoriali aggiuntive: lettura per indicizzazione Google News, RSS diretto NON verificato.
SPECIAL_SITES = [
  {'name': 'SuperBasket', 'url': 'https://www.superbasket.eu/', 'domain':'superbasket.eu', 'origin':'nazionale', 'query':'basket'},
  {'name': 'BasketUniverso', 'url': 'https://www.basketuniverso.it/', 'domain':'basketuniverso.it', 'origin':'nazionale', 'query':'basket'},
  {'name': 'RealOlimpiaMilano', 'url': 'https://realolimpiamilano.com/', 'domain':'realolimpiamilano.com', 'origin':'locale', 'team':'lba-milano', 'query':''},
]
# Pagine pubbliche selezionate nella revisione V3. Tranne Telegram le piattaforme social
# sono solo link consultabili, e NON sono controllate automaticamente.
SOCIAL_PROFILES = [
  {'name':'Mondo a Spicchi — Telegram', 'url':'https://t.me/s/mondoaspicchicanale', 'mode':'pagina pubblica sperimentale'},
  {'name':'Mondo a Spicchi — Instagram', 'url':'https://www.instagram.com/mondoaspicchi/', 'mode':'solo link; profilo da verificare'},
  {'name':'BasketNoLimits — Instagram', 'url':'https://www.instagram.com/_basketnolimits_/', 'mode':'solo link'},
  {'name':'Pep Malaguti — Facebook (profilo)', 'url':'https://www.facebook.com/giuseppe.malaguti.7/', 'mode':'solo link'},
  {'name':'Pep Malaguti — Facebook (pagina)', 'url':'https://www.facebook.com/PepMalaguti/', 'mode':'solo link'},
  {'name':'Pep Malaguti — Instagram', 'url':'https://www.instagram.com/giuseppemalaguti/', 'mode':'solo link'},
  {'name':'Pep Malaguti — X', 'url':'https://x.com/GiuseppeMalagu2', 'mode':'solo link; attività da verificare'},
]

assert len(TEAMS)==36 and len({t.id for t in TEAMS})==36
TEAM_MAP = {t.id: t for t in TEAMS}

# Fonti RSS dirette: i feed possono cambiare o risultare inaccessibili. Sono verificati in esecuzione.
DIRECT_FEEDS = [
    {'name':'Sportando','url':'https://sportando.basketball/feed/','origin':'nazionale'},
    {'name':'PianetaBasket','url':'https://www.pianetabasket.com/rss/','origin':'nazionale'},
    {'name':'Basketinside','url':'https://www.basketinside.com/feed/','origin':'nazionale'},
    {'name':'BolognaBasket','url':'https://www.bolognabasket.org/feed/','origin':'locale'},
    {'name':'MegaBasket','url':'https://www.megabasket.it/feed/','origin':'locale'},
]
NATIONAL_DOMAINS = {'sportando.basketball','pianetabasket.com','basketinside.com','basketmagazine.net', 'gazzetta.it','eurosport.it','skysport.it','superbasket.eu','basketuniverso.it'}
OFFICIAL_LEAGUES = {'legabasket.it','legapallacanestro.com'}

def host_of(url):
    try: return urlparse(url).hostname.lower().removeprefix('www.')
    except Exception: return ''

def is_subdomain(host, domain):
    domain=domain.removeprefix('www.').lower()
    return host == domain or host.endswith('.'+domain)

def classify_source(host, team_id=None):
    if any(is_subdomain(host,d) for d in OFFICIAL_LEAGUES): return 'ufficiale'
    if team_id:
        t=TEAM_MAP.get(team_id)
        if t:
            if t.official and is_subdomain(host,host_of(t.official)): return 'ufficiale'
            if any(is_subdomain(host,x) for x in t.local): return 'locale'
    if any(is_subdomain(host,x) for x in NATIONAL_DOMAINS): return 'nazionale'
    if any(is_subdomain(host,x) for x in {d for t in TEAMS for d in t.local}): return 'locale'
    return 'altre'

def normalize(s):
    import unicodedata
    s=unicodedata.normalize('NFKD',s or '')
    s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()

def match_teams(title, summary='', hinted=None):
    text=normalize(title+' '+summary[:450])
    result=[]
    for t in TEAMS:
        aliases=t.aliases
        if any(re.search(r'(?<!\w)'+re.escape(normalize(a))+r'(?!\w)', text) for a in aliases):
            result.append(t.id)
    # Query locale/ufficiale con abbinamento singolo: accetta contenuti senza il nome nel testo
    if hinted and hinted not in result:
        # La query Google News specifica una squadra, ma verifichiamo almeno un indizio della squadra.
        target=TEAM_MAP[hinted]
        if any(normalize(x) in text for x in [target.name,target.query.split('"')[1] if '"' in target.query else target.name]):
            result.append(hinted)
    return result
