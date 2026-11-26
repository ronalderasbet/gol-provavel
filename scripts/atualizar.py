#!/usr/bin/env python3
"""
Gol Provável — atualização automática.

A cada execução:
  1. Registra o placar dos jogos encerrados (até 7 dias atrás).
  2. Busca os jogos de hoje e de amanhã nas competições configuradas.
  3. Calcula, para cada jogo: placar mais provável, vitória/empate/derrota,
     chance de 1+, 2+ e 3+ gols e de ambos marcarem.
     Jogos que ainda não começaram são recalculados; depois do apito inicial a previsão fica congelada.
  4. Salva tudo em docs/ (o site lê esses arquivos).

Chaves (em Settings > Secrets and variables > Actions):
  APIFOOTBALL_KEY   -> API-Football (todas as competições)
  FOOTBALLDATA_KEY  -> football-data.org (reserva: só algumas ligas)
"""
import json, math, os, re, sys, time, unicodedata, difflib, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DATA_PATH = os.path.join(DOCS, "data.json")
CACHE_PATH = os.path.join(DOCS, "cache.json")
HIST_DIR = os.path.join(DOCS, "history")
RECENT_DAYS = 14          # dias mantidos com todos os detalhes em data.json
STATS_MAX_AGE_H = 6       # estatísticas de liga renovadas a cada 6 horas
RHO = -0.08               # correção de Dixon-Coles para placares baixos
FORM_HALF_LIFE_DAYS = 365 # forma recente: um jogo de 1 ano atrás vale metade de um jogo de hoje
PREV_SEASON_MAX_AGE_D = 30  # jogos da temporada anterior: buscados de novo a cada 30 dias
# (meia-vida e uso da temporada anterior escolhidos por teste em 22 temporadas reais, 6.846 jogos)

# ---------------------------------------------------------------------------
# Competições. af = id na API-Football; country/names = plano B para achar a liga pelo nome;
# fd = código na football-data.org; H = média histórica de gols por time por jogo; hf = fator de mando.
# ---------------------------------------------------------------------------
def L(name, af, country, names, H, hf=1.12, fd=None, cup=False, group="Outras"):
    return dict(name=name, af=af, country=country, names=names, H=H, hf=hf, fd=fd, cup=cup, group=group)

LEAGUES = {
    # Europa — copas
    "ucl":  L("Champions League", 2, "World", ["UEFA Champions League"], 1.55, 1.08, "CL", True, "Copas europeias"),
    "uel":  L("Europa League", 3, "World", ["UEFA Europa League"], 1.40, 1.08, None, True, "Copas europeias"),
    "uecl": L("Conference League", 848, "World", ["UEFA Europa Conference League", "UEFA Conference League"], 1.35, 1.08, None, True, "Copas europeias"),
    # Europa — ligas
    "epl":  L("Premier League (Inglaterra)", 39, "England", ["Premier League"], 1.40, 1.12, "PL", group="Europa"),
    "lal":  L("LaLiga (Espanha)", 140, "Spain", ["La Liga"], 1.30, 1.14, "PD", group="Europa"),
    "lig1": L("Ligue 1 (França)", 61, "France", ["Ligue 1"], 1.40, 1.12, "FL1", group="Europa"),
    "bun":  L("Bundesliga (Alemanha)", 78, "Germany", ["Bundesliga"], 1.55, 1.10, "BL1", group="Europa"),
    "sea":  L("Serie A (Itália)", 135, "Italy", ["Serie A"], 1.30, 1.12, "SA", group="Europa"),
    "tur":  L("Süper Lig (Turquia)", 203, "Turkey", ["Süper Lig", "Super Lig"], 1.45, 1.15, group="Europa"),
    "por":  L("Liga Portugal", 94, "Portugal", ["Primeira Liga"], 1.30, 1.14, "PPL", group="Europa"),
    "ned":  L("Eredivisie (Holanda)", 88, "Netherlands", ["Eredivisie"], 1.55, 1.12, "DED", group="Europa"),
    # Brasil
    "bra":  L("Brasileirão Série A", 71, "Brazil", ["Serie A"], 1.20, 1.20, "BSA", group="Brasil"),
    "brb":  L("Brasileirão Série B", 72, "Brazil", ["Serie B"], 1.10, 1.22, group="Brasil"),
    "cdb":  L("Copa do Brasil", 73, "Brazil", ["Copa Do Brasil"], 1.20, 1.18, group="Brasil"),
    # América do Sul e Central
    "lib":  L("Libertadores", 13, "World", ["CONMEBOL Libertadores"], 1.20, 1.20, cup=False, group="Copas sul-americanas"),
    "sud":  L("Sul-Americana", 11, "World", ["CONMEBOL Sudamericana"], 1.20, 1.20, group="Copas sul-americanas"),
    "arg":  L("Liga Profesional (Argentina)", 128, "Argentina", ["Liga Profesional Argentina", "Primera División"], 1.10, 1.18, group="América Latina"),
    "chi":  L("Primera División (Chile)", 265, "Chile", ["Primera División"], 1.40, 1.15, group="América Latina"),
    "col":  L("Liga BetPlay (Colômbia)", 239, "Colombia", ["Primera A"], 1.15, 1.20, group="América Latina"),
    "uru":  L("Primera División (Uruguai)", 268, "Uruguay", ["Primera División - Apertura", "Primera División - Clausura", "Primera División"], 1.20, 1.10, group="América Latina"),
    "par":  L("Primera División (Paraguai)", 250, "Paraguay", ["Division Profesional - Apertura", "Division Profesional - Clausura", "Primera División"], 1.25, 1.12, group="América Latina"),
    "ecu":  L("LigaPro (Equador)", 242, "Ecuador", ["Liga Pro", "LigaPro Serie A"], 1.25, 1.22, group="América Latina"),
    "per":  L("Liga 1 (Peru)", 281, "Peru", ["Primera División", "Liga 1"], 1.30, 1.25, group="América Latina"),
    "mex":  L("Liga MX (México)", 262, "Mexico", ["Liga MX"], 1.40, 1.15, group="América Latina"),
    "bol":  L("División Profesional (Bolívia)", 344, "Bolivia", ["Primera División", "División Profesional"], 1.55, 1.30, group="América Latina"),
    "ven":  L("Liga FUTVE (Venezuela)", 299, "Venezuela", ["Primera División"], 1.15, 1.18, group="América Latina"),
    # Outras
    "mls":  L("MLS (EUA)", 253, "USA", ["Major League Soccer"], 1.50, 1.15, group="Outras"),
    "sau":  L("Saudi Pro League", 307, "Saudi-Arabia", ["Pro League"], 1.50, 1.08, group="Outras"),
}
AF_TO_KEY = {v["af"]: k for k, v in LEAGUES.items()}
NAME_TO_KEY = {(v["country"].lower(), n.lower()): k for k, v in LEAGUES.items() for n in v["names"]}
FD_TO_KEY = {v["fd"]: k for k, v in LEAGUES.items() if v["fd"]}

ALIASES = {
    "psg": "paris saint germain", "bayern de munique": "bayern munchen", "inter de milao": "inter",
    "atletico de madrid": "atletico madrid", "slavia praga": "slavia praha", "sporting": "sporting cp",
    "estrela vermelha": "crvena zvezda", "sparta praga": "sparta praha", "ofi creta": "ofi",
    "olympique de marseille": "marseille", "celta de vigo": "celta vigo", "copenhagen": "fc copenhagen",
    "nec nijmegen": "nec", "milan": "ac milan", "atletico-mg": "atletico mineiro",
    "inter d'escaldes": "inter club d'escaldes", "egnatia": "egnatia rrogozhine", "saburtalo": "saburtalo tbilisi",
}


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
def _days(a, b):
    """Dias entre duas datas ISO (só a parte AAAA-MM-DD importa)."""
    return (datetime.strptime(a[:10], "%Y-%m-%d") - datetime.strptime(b[:10], "%Y-%m-%d")).days


def build_stats(rows, ref=None, half_life=None):
    """rows = (mandante, visitante, gols_m, gols_v, data ISO).
    Por time: r = contagens reais [J, GP, GC, Jc, GPc, GCc, Jf, GPf, GCf];
              w = as mesmas contagens com peso maior para jogos recentes (forma recente);
              f = últimos 5 resultados (V/E/D, do mais antigo ao mais recente)."""
    half_life = FORM_HALF_LIFE_DAYS if half_life is None else half_life
    ref = ref or max((r[4] for r in rows if len(r) > 4 and r[4]), default=None)
    t, gh, ga, hist = {}, 0, 0, {}
    for row in rows:
        h, a, x, y = row[:4]
        d = row[4] if len(row) > 4 else None
        wt = 1.0
        if half_life and ref and d:
            wt = 0.5 ** (max(0, _days(ref, d)) / half_life)
        for team, gf, gc, home in ((h, x, y, True), (a, y, x, False)):
            e = t.setdefault(team, {"r": [0] * 9, "w": [0.0] * 9})
            idx = (0, 1, 2, 3, 4, 5) if home else (0, 1, 2, 6, 7, 8)
            for arr, inc in ((e["r"], 1), (e["w"], wt)):
                arr[idx[0]] += inc; arr[idx[1]] += gf * inc; arr[idx[2]] += gc * inc
                arr[idx[3]] += inc; arr[idx[4]] += gf * inc; arr[idx[5]] += gc * inc
            hist.setdefault(team, []).append((d or "", "V" if gf > gc else ("E" if gf == gc else "D")))
        gh += x; ga += y
    for team, e in t.items():
        e["w"] = [round(v, 3) for v in e["w"]]
        e["f"] = "".join(r for _, r in sorted(hist[team])[-5:])
    return dict(teams=t, n=len(rows), gh=gh, ga=ga, v=2)


def league_means(key, st):
    Lg = LEAGUES[key]
    w = st["n"] / (st["n"] + 40.0)
    pH, pA = Lg["H"] * Lg["hf"], Lg["H"] * (2 - Lg["hf"])
    oH = st["gh"] / st["n"] if st["n"] else pH
    oA = st["ga"] / st["n"] if st["n"] else pA
    return w * oH + (1 - w) * pH, w * oA + (1 - w) * pA


def predict(key, st, home, away):
    muH, muA = league_means(key, st)
    mu = (muH + muA) / 2
    k = 6 if LEAGUES[key]["cup"] else 5
    empty = {"r": [0] * 9, "w": [0] * 9, "f": ""}
    th, ta = st["teams"].get(home, empty), st["teams"].get(away, empty)
    s, v = th["w"], ta["w"]          # contagens com forma recente
    r = lambda x, g, m: (x + k * m) / (g + k) / m
    att_h = math.sqrt(r(s[1], s[0], mu) * r(s[4], s[3], muH))
    def_h = math.sqrt(r(s[2], s[0], mu) * r(s[5], s[3], muA))
    att_a = math.sqrt(r(v[1], v[0], mu) * r(v[7], v[6], muA))
    def_a = math.sqrt(r(v[2], v[0], mu) * r(v[8], v[6], muH))
    lh = min(5.0, max(0.15, muH * att_h * def_a))
    la = min(5.0, max(0.15, muA * att_a * def_h))
    return dict(score_model(lh, la), sh=th.get("c", th["r"][:3]), sa=ta.get("c", ta["r"][:3]), fh=th.get("f", ""), fa=ta.get("f", ""))


def team_table(key, prev_rows, cur_rows):
    """Simulação da temporada: para cada jogo já encerrado, calcula o que o modelo teria previsto
    usando só os jogos anteriores a ele, e compara com o que aconteceu, time por time."""
    cur = sorted(cur_rows, key=lambda r: (r[4] or "")[:10])
    acc = {}
    i = 0
    while i < len(cur):
        day = (cur[i][4] or "")[:10]
        j = i
        while j < len(cur) and (cur[j][4] or "")[:10] == day:
            j += 1
        st = build_stats(list(prev_rows) + cur[:i], ref=day)
        for h, a, x, y, _ in cur[i:j]:
            p = predict(key, st, h, a)
            pw, pd, pl = p["hda"]
            for team, gf, gc, lf, lc, w, d, home in ((h, x, y, p["lh"], p["la"], pw, pd, True), (a, y, x, p["la"], p["lh"], pl, pd, False)):
                e = acc.setdefault(team, [0, 0, 0.0, 0, 0.0, 0, 0.0, 0.0, 0.0])
                pts = 3 if gf > gc else (1 if gf == gc else 0)
                xpts = 3 * w + d
                e[0] += 1; e[1] += gf; e[2] += lf; e[3] += gc; e[4] += lc; e[5] += pts; e[6] += xpts
                e[7] += 9 * w + d - xpts ** 2          # variância dos pontos
        i = j
    out = []
    for team, (jg, gp, xgp, gc, xgc, pts, xpts, vpts, _) in acc.items():
        z = lambda real, prev, var: round((real - prev) / math.sqrt(var), 2) if var > 0 else 0.0
        out.append(dict(t=team, j=jg, gp=gp, xgp=round(xgp, 1), gc=gc, xgc=round(xgc, 1), pts=pts, xpts=round(xpts, 1),
                        zg=z(gp, xgp, xgp), zc=z(gc, xgc, xgc), zp=z(pts, xpts, vpts)))
    return sorted(out, key=lambda r: -(r["pts"] - r["xpts"]))


def score_model(lh, la, N=10):
    pois = lambda l, n: math.exp(-l) * l ** n / math.factorial(n)
    M = [[pois(lh, i) * pois(la, j) for j in range(N + 1)] for i in range(N + 1)]
    M[0][0] *= max(0.0, 1 - lh * la * RHO); M[0][1] *= max(0.0, 1 + lh * RHO)
    M[1][0] *= max(0.0, 1 + la * RHO);     M[1][1] *= max(0.0, 1 - RHO)
    tot = sum(map(sum, M))
    M = [[x / tot for x in row] for row in M]
    cells = [(M[i][j], i, j) for i in range(N + 1) for j in range(N + 1)]
    P = lambda f: sum(p for p, i, j in cells if f(i, j))
    top = sorted(cells, reverse=True)[:3]
    R = lambda x: round(x, 4)
    return dict(lh=round(lh, 3), la=round(la, 3),
                p1=R(P(lambda i, j: i + j >= 1)), p2=R(P(lambda i, j: i + j >= 2)), p3=R(P(lambda i, j: i + j >= 3)),
                btts=R(P(lambda i, j: i >= 1 and j >= 1)),
                hda=[R(P(lambda i, j: i > j)), R(P(lambda i, j: i == j)), R(P(lambda i, j: i < j))],
                sc=[[i, j, R(p)] for p, i, j in top])


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    s = ALIASES.get(s, s)
    s = re.sub(r"\b(fc|cf|ac|as|sc|afc|cd|ca|fk|sk|nk|bk|if|aif|kv|kaa|club|de|clube|atletico)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


class ProviderError(Exception):
    pass


def http_json(url, headers):
    req = urllib.request.Request(url, headers={"User-Agent": "gol-provavel/2.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        raise ProviderError("HTTP %s: %s" % (e.code, e.read()[:300].decode(errors="ignore")))
    except urllib.error.URLError as e:
        raise ProviderError("sem conexão: %s" % e)


# ---------------------------------------------------------------------------
# Fonte 1: API-Football
# ---------------------------------------------------------------------------
class APIFootball:
    name = "API-Football"
    BASE = "https://v3.football.api-sports.io"
    FINISHED = {"FT", "AET", "PEN"}
    VOID = {"PST", "CANC", "ABD", "AWD", "WO"}

    def __init__(self, key):
        self.h = {"x-apisports-key": key}
        self.calls, self.remaining, self.plan, self.req = 0, None, None, None

    def get(self, path, **q):
        js, hd = http_json(self.BASE + path + "?" + urllib.parse.urlencode(q), self.h)
        self.calls += 1
        rem = {k.lower(): v for k, v in hd.items()}.get("x-ratelimit-requests-remaining")
        if rem is not None:
            self.remaining = int(rem)
        if js.get("errors"):
            raise ProviderError(json.dumps(js["errors"], ensure_ascii=False))
        return js.get("response", [])

    def fixtures_on(self, date):
        out = []
        for f in self.get("/fixtures", date=date, timezone="America/Sao_Paulo"):
            lg = f["league"]
            key = AF_TO_KEY.get(lg["id"]) or NAME_TO_KEY.get(((lg.get("country") or "").lower(), (lg.get("name") or "").lower()))
            if not key:
                continue
            st = f["fixture"]["status"]["short"]
            ft = (f.get("score") or {}).get("fulltime") or {}
            res = [ft["home"], ft["away"]] if st in self.FINISHED and ft.get("home") is not None else ("adiado" if st in self.VOID else None)
            out.append(dict(fid="af%d" % f["fixture"]["id"], lg=key, lid=lg["id"], season=lg["season"], ko=f["fixture"]["date"],
                            h=f["teams"]["home"]["name"], a=f["teams"]["away"]["name"], res=res))
        return out

    def finished_in(self, f, season=None):
        rows = []
        for x in self.get("/fixtures", league=f["lid"], season=season or f["season"], status="FT-AET-PEN"):
            ft = (x.get("score") or {}).get("fulltime") or {}
            if ft.get("home") is not None:
                rows.append((x["teams"]["home"]["name"], x["teams"]["away"]["name"], ft["home"], ft["away"], x["fixture"]["date"]))
        return rows


# ---------------------------------------------------------------------------
# Fonte 2: football-data.org (reserva)
# ---------------------------------------------------------------------------
class FootballData:
    name = "football-data.org"
    BASE = "https://api.football-data.org/v4"

    def __init__(self, key):
        self.h = {"X-Auth-Token": key}
        self.calls, self.remaining, self._cache = 0, None, {}

    def get(self, path, **q):
        if self.calls:
            time.sleep(6.5)  # limite: 10 chamadas por minuto
        self.calls += 1
        js, _ = http_json(self.BASE + path + ("?" + urllib.parse.urlencode(q) if q else ""), self.h)
        return js

    @staticmethod
    def score(m):
        sc = m.get("score") or {}
        reg = sc.get("regularTime") or sc.get("fullTime") or {}
        return None if reg.get("home") is None else [reg["home"], reg["away"]]

    def fixtures_on(self, date):
        d = datetime.strptime(date, "%Y-%m-%d")
        rng = ((d - timedelta(days=1)).strftime("%Y-%m-%d"), (d + timedelta(days=1)).strftime("%Y-%m-%d"))
        if rng not in self._cache:
            self._cache[rng] = self.get("/matches", dateFrom=rng[0], dateTo=rng[1]).get("matches", [])
        out = []
        for m in self._cache[rng]:
            key = FD_TO_KEY.get((m.get("competition") or {}).get("code"))
            if not key:
                continue
            ko = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(TZ)
            if ko.strftime("%Y-%m-%d") != date:
                continue
            st = m.get("status")
            res = self.score(m) if st == "FINISHED" else ("adiado" if st in ("POSTPONED", "CANCELLED", "SUSPENDED") else None)
            out.append(dict(fid="fd%d" % m["id"], lg=key, lid=LEAGUES[key]["fd"], season=int((m.get("season") or {}).get("startDate", "2000")[:4]),
                            ko=ko.isoformat(), h=m["homeTeam"]["name"], a=m["awayTeam"]["name"], res=res))
        return out

    def finished_in(self, f, season=None):
        q = {"status": "FINISHED"}
        if season:
            q["season"] = season
        js = self.get("/competitions/%s/matches" % f["lid"], **q)
        return [(m["homeTeam"]["name"], m["awayTeam"]["name"], *self.score(m), m.get("utcDate", "")) for m in js.get("matches", []) if self.score(m)]


# ---------------------------------------------------------------------------
# Atualização
# ---------------------------------------------------------------------------
def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def save(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent, separators=(",", ":") if indent is None else None)


def pick_provider(today):
    errs = []
    for env, cls in (("APIFOOTBALL_KEY", APIFootball), ("FOOTBALLDATA_KEY", FootballData)):
        key = os.environ.get(env, "").strip()
        if not key:
            continue
        p = cls(key)
        if cls is APIFootball:
            try:  # /status não conta na cota diária
                js, _ = http_json(APIFootball.BASE + "/status", p.h)
                r = js.get("response") or {}
                sub, req = r.get("subscription") or {}, r.get("requests") or {}
                log("Conta API-Football: plano %s · ativa: %s · requisições hoje: %s de %s"
                    % (sub.get("plan", "?"), sub.get("active", "?"), req.get("current", "?"), req.get("limit_day", "?")))
                p.plan = sub.get("plan")
                p.req = "%s de %s" % (req.get("current", "?"), req.get("limit_day", "?"))
                if js.get("errors"):
                    log("AVISO da API-Football: %s" % json.dumps(js["errors"], ensure_ascii=False))
            except ProviderError as e:
                log("AVISO: não consegui consultar a conta -> %s" % e)
        try:
            fx = p.fixtures_on(today)
            log("Fonte: %s · %d jogos hoje nas competições acompanhadas" % (p.name, len(fx)))
            return p, {today: fx}
        except ProviderError as e:
            errs.append("%s: %s" % (p.name, e)); log("AVISO: %s falhou -> %s" % (p.name, e))
    raise SourceFailure(friendly(errs))


class SourceFailure(Exception):
    pass


def friendly(errs):
    """Traduz o erro técnico em instruções simples, mostradas dentro do app."""
    raw = " | ".join(errs).lower()
    if not errs:
        return ("Nenhuma chave de dados foi encontrada. No GitHub, vá em Settings > Secrets and variables > Actions "
                "e crie o segredo com o nome exato APIFOOTBALL_KEY, colando a chave da API-Football.")
    if "season" in raw or "free plan" in raw:
        return ("O plano grátis da API-Football não libera a temporada atual. Opções: cadastrar a chave grátis da "
                "football-data.org como segredo FOOTBALLDATA_KEY (cobre ligas europeias e o Brasileirão) ou assinar o "
                "plano Pro da API-Football para liberar todas as competições.")
    if "token" in raw or "application key" in raw or "key" in raw and ("invalid" in raw or "missing" in raw) or "401" in raw or "403" in raw:
        return ("A chave da API não foi aceita. Copie de novo a API-KEY no painel da API-Football e, no GitHub, "
                "atualize o segredo APIFOOTBALL_KEY (Settings > Secrets and variables > Actions > lápis ao lado do nome).")
    if "limit" in raw or "requests" in raw or "429" in raw:
        return "O limite diário de requisições da API foi atingido. O app tenta de novo automaticamente amanhã."
    if "conex" in raw or "timed out" in raw or "http 5" in raw:
        return "O servidor de dados não respondeu. Isso costuma ser passageiro; o app tenta de novo na próxima atualização."
    return "Não foi possível buscar os dados. Detalhe técnico: " + " | ".join(errs)[:300]


def find_day(data, date):
    for d in data["days"]:
        if d["date"] == date:
            return d
    d = {"date": date, "matches": []}
    data["days"].append(d)
    return d


def link(existing, f):
    for m in existing:
        if m.get("fid") == f["fid"]:
            return m
    best, score = None, 0.0
    for m in existing:
        if m.get("fid") or m["lg"] != f["lg"]:
            continue
        a, b = sim(m.get("hk", m["h"]), f["h"]), sim(m.get("ak", m["a"]), f["a"])
        if min(a, b) >= 0.4 and (a + b) / 2 > score:
            best, score = m, (a + b) / 2
    return best if score >= 0.6 else None


COMPACT_KEYS = ("t", "lg", "h", "a", "res", "p1", "p2", "p3", "btts", "hda", "sc")


def archive(data):
    """Move dias com mais de RECENT_DAYS para docs/history/AAAA-MM.json (formato enxuto)."""
    cut = (datetime.now(TZ) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    keep, moved = [], {}
    for d in data["days"]:
        if d["date"] >= cut:
            keep.append(d); continue
        ms = [{k: m[k] for k in COMPACT_KEYS if k in m} for m in d["matches"] if m.get("res") != "adiado"]
        for m in ms:
            if "sc" in m:
                m["sc"] = m["sc"][:1]
        moved.setdefault(d["date"][:7], []).append({"date": d["date"], "matches": ms})
    for month, days in moved.items():
        path = os.path.join(HIST_DIR, month + ".json")
        h = load(path, {"days": []})
        byd = {x["date"]: x for x in h["days"]}
        for x in days:
            byd[x["date"]] = x
        h["days"] = sorted(byd.values(), key=lambda x: x["date"])
        save(path, h)
        log("Arquivado: %s (%d dias)" % (month, len(days)))
    data["days"] = keep
    months = set(data.get("months", [])) | set(moved)
    data["months"] = sorted(m for m in months if os.path.exists(os.path.join(HIST_DIR, m + ".json")))


def main():
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    new_dates = [today, (now + timedelta(days=1)).strftime("%Y-%m-%d")]
    data = load(DATA_PATH, {"days": []})
    cache = load(CACHE_PATH, {})
    data.setdefault("leagues", {})

    floor = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    pending = sorted({d["date"] for d in data["days"] if floor <= d["date"] < today
                      and any(m.get("res") is None for m in d["matches"])})

    try:
        prov, fx = pick_provider(today)
    except SourceFailure as e:
        log("PROBLEMA: %s" % e)
        data.update(error=str(e), error_at=now.strftime("%d/%m às %H:%M"))
        data.setdefault("updated", today)
        save(DATA_PATH, data, indent=None)
        log("O site será publicado mesmo assim, mostrando este aviso dentro do app.")
        return
    data.pop("error", None); data.pop("error_at", None)
    for date in pending + new_dates:
        if date not in fx:
            try:
                fx[date] = prov.fixtures_on(date)
            except ProviderError as e:
                log("AVISO: não consegui buscar %s -> %s" % (date, e)); fx[date] = []

    # 1) placares
    filled = 0
    for date in pending:
        day = find_day(data, date)
        for f in fx[date]:
            m = link(day["matches"], f)
            if m and m.get("res") is None and f["res"] is not None:
                m["res"], m["fid"] = f["res"], f["fid"]; filled += 1
    log("Placares registrados: %d" % filled)

    # 2) estatísticas (reaproveita por até STATS_MAX_AGE_H horas)
    stats, force, fails = {}, os.environ.get("FORCE_STATS") == "1", []
    for f in {(f["lg"], f["season"]): f for d in new_dates for f in fx[d]}.values():
        ck = "%s|%s" % (f["lg"], f["season"])
        c = cache.get(ck)
        fresh = c and c.get("st", {}).get("v") == 2 and (now - datetime.fromisoformat(c["at"])).total_seconds() < STATS_MAX_AGE_H * 3600
        if fresh and not force:
            stats[f["lg"]] = c["st"]; continue
        prev_rows = []
        pk = "prev|%s|%s" % (f["lg"], f["season"])
        pc = cache.get(pk)
        if pc and (now - datetime.fromisoformat(pc["at"])).days < PREV_SEASON_MAX_AGE_D:
            prev_rows = [tuple(r) for r in pc["rows"]]
        else:
            try:
                prev_rows = prov.finished_in(f, season=int(f["season"]) - 1)
                cache[pk] = {"at": now.isoformat(), "rows": [list(r) for r in prev_rows]}
                log("%-32s %4d jogos da temporada anterior" % (LEAGUES[f["lg"]]["name"], len(prev_rows)))
            except ProviderError as e:
                log("Aviso: sem temporada anterior de %s (segue só com a atual) -> %s" % (LEAGUES[f["lg"]]["name"], str(e)[:120]))
                if pc:
                    prev_rows = [tuple(r) for r in pc["rows"]]
        try:
            cur_rows = prov.finished_in(f)
            st = build_stats(prev_rows + cur_rows, ref=now.isoformat())
            cur_only = build_stats(cur_rows, half_life=0)["teams"]
            for team, e in st["teams"].items():
                e["c"] = cur_only.get(team, {"r": [0, 0, 0]})["r"][:3]   # só a temporada atual, para exibir
            st["n_cur"] = len(cur_rows)
            try:  # estatística "times x previsão" (simulação da temporada); nunca derruba a atualização
                data.setdefault("teams", {})[f["lg"]] = {"at": today, "rows": team_table(f["lg"], prev_rows, cur_rows)}
            except Exception as e:  # noqa: BLE001
                log("Aviso: não consegui montar a tabela de times de %s -> %s" % (LEAGUES[f["lg"]]["name"], e))
            st["obs_cur"] = round(sum(r[2] + r[3] for r in cur_rows) / len(cur_rows), 2) if cur_rows else None
        except ProviderError as e:
            log("AVISO: sem estatísticas de %s -> %s" % (LEAGUES[f["lg"]]["name"], e))
            fails.append((LEAGUES[f["lg"]]["name"], str(e)))
            if c and c.get("st", {}).get("v") == 2:
                stats[f["lg"]] = c["st"]
            continue
        stats[f["lg"]] = st
        cache[ck] = {"at": now.isoformat(), "st": st}
        log("%-32s %4d jogos na temporada atual" % (LEAGUES[f["lg"]]["name"], st.get("n_cur", st["n"])))
    for key, st in stats.items():
        muH, muA = league_means(key, st)
        data["leagues"][key] = dict(name=LEAGUES[key]["name"], group=LEAGUES[key]["group"],
                                    obs=st.get("obs_cur") or (round((st["gh"] + st["ga"]) / st["n"], 2) if st["n"] else None),
                                    mu=round(muH + muA, 2), n=st.get("n_cur", st["n"]))

    # 3) jogos de hoje e amanhã
    added = upd = 0
    for date in new_dates:
        day = find_day(data, date)
        for f in fx[date]:
            m = link(day["matches"], f)
            if m is None:
                if f["res"] == "adiado" or f["lg"] not in stats:
                    continue
                m = dict(id="%s-%d" % (date, len(day["matches"])), lg=f["lg"], h=f["h"], a=f["a"], res=None)
                day["matches"].append(m); added += 1
            ko = datetime.fromisoformat(f["ko"])
            m.update(fid=f["fid"], ko=f["ko"], hk=f["h"], ak=f["a"], t=ko.astimezone(TZ).strftime("%H:%M"))
            if f["res"] is not None:
                m["res"] = f["res"]
            if ko > now and f["lg"] in stats:
                m.update(predict(f["lg"], stats[f["lg"]], f["h"], f["a"])); upd += 1
    log("Jogos novos: %d · previsões calculadas: %d" % (added, upd))

    for d in data["days"]:
        d["matches"] = sorted([m for m in d["matches"] if "p1" in m], key=lambda m: (m.get("t", ""), m["h"]))
    data["days"] = sorted([d for d in data["days"] if d["matches"]], key=lambda d: d["date"])
    archive(data)

    old_t = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    data["teams"] = {k: v for k, v in data.get("teams", {}).items() if v.get("at", "") >= old_t}
    cut = (now - timedelta(days=3)).isoformat()
    cut_prev = (now - timedelta(days=PREV_SEASON_MAX_AGE_D + 5)).isoformat()
    cache = {k: v for k, v in cache.items() if v["at"] >= (cut_prev if k.startswith("prev|") else cut)}
    found = {d: len(fx.get(d, [])) for d in new_dates}
    leagues_found = sorted({LEAGUES[f["lg"]]["name"] for d in new_dates for f in fx.get(d, [])})
    data["diag"] = dict(plan=getattr(prov, "plan", None), req=getattr(prov, "req", None),
                        found_today=found[new_dates[0]], found_tomorrow=found[new_dates[1]],
                        leagues_found=leagues_found, leagues_ok=sorted(LEAGUES[k]["name"] for k in stats),
                        leagues_fail=[n for n, _ in fails], fail_reason=friendly([fails[0][1]]) if fails else None,
                        added=added, updated=upd)
    data.pop("warning", None)
    if sum(found.values()) and not stats:
        data["error"] = friendly([fails[0][1]]) if fails else "Os jogos foram encontrados, mas não consegui as estatísticas das competições."
        data["error_at"] = now.strftime("%d/%m às %H:%M")
    elif fails:
        data["warning"] = "%d competição(ões) ficaram sem previsão: %s. Motivo: %s" % (len(fails), ", ".join(n for n, _ in fails[:6]), friendly([fails[0][1]]))
    elif not sum(found.values()):
        data["warning"] = ("A API respondeu, mas não trouxe nenhum jogo das competições acompanhadas para hoje e amanhã. "
                           "Se isso se repetir em dias com rodada, o plano da API pode estar limitando as datas.")
    data.update(updated=today, updated_time=now.strftime("%H:%M"), source=prov.name,
                quota=prov.remaining, version=2)
    save(DATA_PATH, data, indent=None)
    save(CACHE_PATH, cache)
    log("Requisições usadas: %d%s" % (prov.calls, "" if prov.remaining is None else " · restantes hoje: %d" % prov.remaining))


if __name__ == "__main__":
    main()
