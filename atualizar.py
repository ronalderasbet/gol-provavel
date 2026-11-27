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
ODDS_MAX_AGE_H = 3        # odds: a API atualiza a cada 3 horas; buscamos no mesmo ritmo
VALUE_MIN = 0.05          # destaque de "valor" a partir de +5% (chance do app × melhor odd − 1)
INJ_MAX_AGE_H = 3         # desfalques: renovados a cada 3 horas
PLAYER_MAX_AGE_D = 7      # estatísticas de jogadores desfalcados: renovadas a cada 7 dias
PLAYER_CALLS_MAX = 150    # teto de consultas de jogadores por execução (protege a cota)
STRENGTH_STRETCH = 1.10   # estica 10% a diferença de força entre os times: corrige o favorito subestimado nos
                          # confrontos desiguais (ajustado em 2024-25, confirmado em 2025-26)
TB_MIN_GAMES = 5          # sinal "Top 3 x 5 últimos" só depois de cada time ter 5 jogos na temporada
TB_EXCLUDE = {"ucl", "uel", "uecl", "cdb", "lib", "sud"}   # copas: sem tabela de pontos corridos
GOALS_SHRINK = 0.19       # puxa o total de gols esperado 19% para a média da liga (corrige excesso de confiança
                          # nos mercados de gols; ajustado em 2024-25 e confirmado em 2025-26, 4.706 jogos)
# (meia-vida e uso da temporada anterior escolhidos por teste em 22 temporadas reais, 6.846 jogos)
MIX_W = 0.5               # previsão combinada (experimental): metade modelo atual, metade Dixon-Coles completo
DC_TAU = 8.0              # Dixon-Coles completo: força do puxão para a média (≈ 8 jogos de "time médio")
DC_HALF_LIFE = 365        # Dixon-Coles completo: meia-vida dos jogos, em dias
# (teste em 22 temporadas: a mistura empatou em 2024-25 e melhorou 2025-26, 2023-24 e o Brasileirão 2025)

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
    return dict(teams=t, n=len(rows), gh=gh, ga=ga, v=3)


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
    lh = muH * att_h * def_a
    la = muA * att_a * def_h
    tot, mean_tot = lh + la, muH + muA
    if tot > 0:
        f = (mean_tot + (1 - GOALS_SHRINK) * (tot - mean_tot)) / tot
        lh, la = lh * f, la * f
    if lh > 0 and la > 0 and STRENGTH_STRETCH != 1:
        tot, r = lh + la, (lh / la) ** STRENGTH_STRETCH
        lh = tot * r / (1 + r)
        la = tot - lh
    lh, la = min(5.0, max(0.15, lh)), min(5.0, max(0.15, la))
    return dict(score_model(lh, la), sh=th.get("c", th["r"][:3]), sa=ta.get("c", ta["r"][:3]), fh=th.get("f", ""), fa=ta.get("f", ""))


def fit_dc(rows, ref, half_life=DC_HALF_LIFE, tau=DC_TAU):
    """Dixon-Coles completo: acha ao mesmo tempo o ataque e a defesa de todos os times da liga que melhor
    explicam os placares, cada gol comparado com a força de quem estava do outro lado.
    Jogos antigos pesam menos (meia-vida) e cada força é puxada para a média (tau), como no modelo atual."""
    R = []
    for row in rows:
        h, a, x, y = row[:4]
        d = row[4] if len(row) > 4 else None
        w = 0.5 ** (max(0, _days(ref, d)) / half_life) if (half_life and d) else 1.0
        R.append((h, a, x, y, w))
    teams = sorted({r[0] for r in R} | {r[1] for r in R})
    if len(R) < 10 or len(teams) < 4:
        return None
    att = {t: 0.0 for t in teams}; dfn = {t: 0.0 for t in teams}
    c, ha = 0.25, 0.15
    for _ in range(80):
        mx = 0.0
        for which in ("att", "dfn", "c"):
            oS = dict.fromkeys(teams, 0.0); eS = dict.fromkeys(teams, 0.0)
            oC = dict.fromkeys(teams, 0.0); eC = dict.fromkeys(teams, 0.0)
            sx = sy = slh = sla = 0.0
            for h, a, x, y, w in R:
                lh = math.exp(c + ha + att[h] - dfn[a]); la = math.exp(c + att[a] - dfn[h])
                oS[h] += w * x; eS[h] += w * lh; oS[a] += w * y; eS[a] += w * la
                oC[a] += w * x; eC[a] += w * lh; oC[h] += w * y; eC[h] += w * la
                sx += w * x; sy += w * y; slh += w * lh; sla += w * la
            if which == "att":
                for t in teams:
                    st = (oS[t] - eS[t] - tau * att[t]) / (eS[t] + tau); att[t] += st; mx = max(mx, abs(st))
            elif which == "dfn":
                for t in teams:
                    st = (eC[t] - oC[t] - tau * dfn[t]) / (eC[t] + tau); dfn[t] += st; mx = max(mx, abs(st))
            elif slh + sla > 0 and sx + sy > 0:
                st = math.log((sx + sy) / (slh + sla)); c += st; mx = max(mx, abs(st))
                if sx > 0 and slh > 0:
                    s2 = math.log((sx / slh) / ((sx + sy) / (slh + sla))); ha += s2; mx = max(mx, abs(s2))
        if mx < 1e-5:
            break
    return dict(c=round(c, 5), ha=round(ha, 5), att={t: round(v, 5) for t, v in att.items()},
                dfn={t: round(v, 5) for t, v in dfn.items()})


def predict_mix(key, st, home, away, base):
    """Previsão combinada (experimental): média das tabelas de placares do modelo atual e do Dixon-Coles completo.
    base = resultado de predict() para o mesmo jogo. Devolve None quando a liga ainda não tem o ajuste."""
    dc = st.get("dc")
    if not dc or "lh" not in base:
        return None
    lh = math.exp(dc["c"] + dc["ha"] + dc["att"].get(home, 0.0) - dc["dfn"].get(away, 0.0))
    la = math.exp(dc["c"] + dc["att"].get(away, 0.0) - dc["dfn"].get(home, 0.0))
    muH, muA = league_means(key, st)
    tot, mean_tot = lh + la, muH + muA
    if tot > 0:
        f = (mean_tot + (1 - GOALS_SHRINK) * (tot - mean_tot)) / tot
        lh, la = lh * f, la * f
    if lh > 0 and la > 0 and STRENGTH_STRETCH != 1:
        tot, r = lh + la, (lh / la) ** STRENGTH_STRETCH
        lh = tot * r / (1 + r)
        la = tot - lh
    lh, la = min(5.0, max(0.15, lh)), min(5.0, max(0.15, la))
    M1, M2 = score_matrix(base["lh"], base["la"]), score_matrix(lh, la)
    M = [[(1 - MIX_W) * p + MIX_W * q for p, q in zip(r1, r2)] for r1, r2 in zip(M1, M2)]
    out = score_model((1 - MIX_W) * base["lh"] + MIX_W * lh, (1 - MIX_W) * base["la"] + MIX_W * la, M=M)
    return {k: out[k] for k in ("lh", "la", "p1", "p2", "p3", "btts", "hda", "sc", "sg")}


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


ODDS_MARKETS = {  # nossa chave -> (nome da aposta na API, valor na API, grupo de resultados da mesma aposta)
    "home": ("match winner", "home", "1x2"), "draw": ("match winner", "draw", "1x2"), "away": ("match winner", "away", "1x2"),
    "o15": ("goals over/under", "over 1.5", "ou15"), "u15": ("goals over/under", "under 1.5", "ou15"),
    "o25": ("goals over/under", "over 2.5", "ou25"), "u25": ("goals over/under", "under 2.5", "ou25"),
    "by": ("both teams score", "yes", "btts"), "bn": ("both teams score", "no", "btts"),
}


def parse_odds(bookmakers):
    """Recebe a lista de casas (formato API-Football) e devolve, por mercado:
    p = chance implícita de consenso (mediana entre as casas, sem a margem de cada uma),
    best = melhor odd encontrada, bk = casa que paga a melhor odd, n = número de casas."""
    fair, best = {}, {}
    for b in bookmakers or []:
        groups = {}
        for bet in b.get("bets") or []:
            name = (bet.get("name") or "").strip().lower().replace("both teams to score", "both teams score")
            for v in bet.get("values") or []:
                try:
                    odd = float(v.get("odd"))
                except (TypeError, ValueError):
                    continue
                if odd <= 1.0:
                    continue
                val = str(v.get("value") or "").strip().lower()
                for key, (bn, bv, grp) in ODDS_MARKETS.items():
                    if name == bn and val == bv:
                        groups.setdefault(grp, {})[key] = odd
        for grp, outs in groups.items():
            need = {k for k, x in ODDS_MARKETS.items() if x[2] == grp}
            if set(outs) != need:
                continue  # sem todos os resultados da aposta não dá para tirar a margem
            inv = {k: 1 / o for k, o in outs.items()}
            tot = sum(inv.values())
            for k, o in outs.items():
                fair.setdefault(k, []).append(inv[k] / tot)
                if o > best.get(k, (0, ""))[0]:
                    best[k] = (o, b.get("name") or "")
    out = {}
    for k, ps in fair.items():
        out[k] = {"p": round(_median(ps), 4), "best": round(best[k][0], 2), "bk": best[k][1], "n": len(ps)}
    return out


def model_prob(m, key):
    """Chance do app para cada mercado de odds."""
    hda = m.get("hda") or [None, None, None]
    return {"home": hda[0], "draw": hda[1], "away": hda[2],
            "o15": m.get("p2"), "u15": None if m.get("p2") is None else 1 - m["p2"],
            "o25": m.get("p3"), "u25": None if m.get("p3") is None else 1 - m["p3"],
            "by": m.get("btts"), "bn": None if m.get("btts") is None else 1 - m["btts"]}.get(key)


def attach_value(m):
    """Calcula o valor (chance do app × melhor odd − 1) de cada mercado com odds."""
    for key, o in (m.get("odds") or {}).get("mk", {}).items():
        pm = model_prob(m, key)
        o["v"] = None if pm is None else round(pm * o["best"] - 1, 4)


def player_importance(pl, team_stats):
    """Importância de um jogador para o time, a partir das estatísticas da temporada.
    att = parcela dos gols do time ligados a ele (gols + meia assistência); reg = titular frequente."""
    j, gp = (team_stats or [0, 0, 0])[0], (team_stats or [0, 0, 0])[1]
    mins = pl.get("min", 0)
    reg = j > 0 and mins >= 0.5 * 90 * j
    att = (pl.get("g", 0) + 0.5 * pl.get("a", 0)) / (1.35 * gp) if gp > 0 else 0.0
    return round(min(0.5, att), 3), bool(reg)


def injury_adjust(m, inj, stats_lg):
    """Previsão experimental com desfalques. Regras conservadoras (o reserva recupera metade do que se perde):
    ataque do time cai metade da parcela de gols dos ausentes (máx. −25%);
    cada titular frequente de defesa ausente aumenta os gols do adversário em 5% (goleiro: 8%; máx. +20%).
    'Questionable' (dúvida) conta pela metade."""
    if not inj or "lh" not in m:
        return None
    factors = {}
    for side in ("h", "a"):
        att_loss, def_loss = 0.0, 0.0
        for p in inj.get(side, []):
            w = 1.0 if p.get("t") == "M" else 0.5
            att_loss += w * p.get("att", 0)
            if p.get("reg"):
                if p.get("pos") == "G":
                    def_loss += w * 0.08
                elif p.get("pos") == "D":
                    def_loss += w * 0.05
        factors[side] = (max(0.75, 1 - 0.5 * att_loss), min(1.20, 1 + def_loss))
    lh = m["lh"] * factors["h"][0] * factors["a"][1]
    la = m["la"] * factors["a"][0] * factors["h"][1]
    if abs(lh - m["lh"]) < 1e-4 and abs(la - m["la"]) < 1e-4:
        return None
    return score_model(min(5.0, max(0.15, lh)), min(5.0, max(0.15, la)))


def standings(rows):
    """Classificação por pontos, saldo e gols marcados: {time: [posição, jogos]}."""
    t = {}
    for h, a, x, y, *_ in rows:
        for team, gf, gc in ((h, x, y), (a, y, x)):
            e = t.setdefault(team, [0, 0, 0, 0])
            e[0] += 3 if gf > gc else (1 if gf == gc else 0); e[1] += gf - gc; e[2] += gf; e[3] += 1
    order = sorted(t, key=lambda k: (-t[k][0], -t[k][1], -t[k][2]))
    return {team: [i + 1, t[team][3]] for i, team in enumerate(order)}


def top_bottom(key, st, home, away):
    """Sinal de jogo desigual: 'home' = Top 3 em casa contra um dos 5 últimos; 'away' = Top 3 visitando um dos 5 últimos."""
    if key in TB_EXCLUDE or not st or not st.get("rank"):
        return None, None
    rk, n = st["rank"], len(st["rank"])
    if home not in rk or away not in rk or n < 10:
        return None, None
    (rh, gh), (ra, ga) = rk[home], rk[away]
    pos = [rh, ra, n]
    if gh < TB_MIN_GAMES or ga < TB_MIN_GAMES:
        return None, pos
    if rh <= 3 and ra >= n - 4:
        return "home", pos
    if ra <= 3 and rh >= n - 4:
        return "away", pos
    return None, pos


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


def score_matrix(lh, la, N=10):
    pois = lambda l, n: math.exp(-l) * l ** n / math.factorial(n)
    M = [[pois(lh, i) * pois(la, j) for j in range(N + 1)] for i in range(N + 1)]
    M[0][0] *= max(0.0, 1 - lh * la * RHO); M[0][1] *= max(0.0, 1 + lh * RHO)
    M[1][0] *= max(0.0, 1 + la * RHO);     M[1][1] *= max(0.0, 1 - RHO)
    tot = sum(map(sum, M))
    return [[x / tot for x in row] for row in M]


def score_model(lh, la, N=10, M=None):
    M = M or score_matrix(lh, la, N)
    cells = [(M[i][j], i, j) for i in range(N + 1) for j in range(N + 1)]
    P = lambda f: sum(p for p, i, j in cells if f(i, j))
    top = sorted(cells, reverse=True)[:3]
    R = lambda x: round(x, 4)
    hda = [P(lambda i, j: i > j), P(lambda i, j: i == j), P(lambda i, j: i < j)]
    fav = max(range(3), key=lambda k: hda[k])
    inside = {0: lambda i, j: i > j, 1: lambda i, j: i == j, 2: lambda i, j: i < j}[fav]
    sug = max(c for c in cells if inside(c[1], c[2]))   # placar sugerido: o mais provável dentro do resultado favorito
    return dict(lh=round(lh, 3), la=round(la, 3),
                p1=R(P(lambda i, j: i + j >= 1)), p2=R(P(lambda i, j: i + j >= 2)), p3=R(P(lambda i, j: i + j >= 3)),
                btts=R(P(lambda i, j: i >= 1 and j >= 1)),
                hda=[R(P(lambda i, j: i > j)), R(P(lambda i, j: i == j)), R(P(lambda i, j: i < j))],
                sc=[[i, j, R(p)] for p, i, j in top], sg=[sug[1], sug[2], R(sug[0])])


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
                            h=f["teams"]["home"]["name"], a=f["teams"]["away"]["name"], res=res,
                            hid=f["teams"]["home"].get("id"), aid=f["teams"]["away"].get("id")))
        return out

    def injuries(self, fids):
        """Desfalques de até 20 jogos por chamada: {fid: [{id, name, team, type, reason}]}."""
        out = {f: [] for f in fids}
        for i in range(0, len(fids), 20):
            chunk = fids[i:i + 20]
            for it in self.get("/injuries", ids="-".join(f[2:] for f in chunk)):
                fid = "af%s" % (it.get("fixture") or {}).get("id")
                pl = it.get("player") or {}
                if fid in out and pl.get("id"):
                    out[fid].append(dict(id=pl["id"], name=pl.get("name") or "", team=(it.get("team") or {}).get("name") or "",
                                         type=pl.get("type") or "", reason=pl.get("reason") or ""))
        return out

    def player_season(self, pid, season, lid):
        """Gols, assistências, minutos e posição do jogador na competição (ou na temporada toda)."""
        resp = self.get("/players", id=pid, season=season)
        stats = (resp[0].get("statistics") if resp else None) or []
        same = [x for x in stats if (x.get("league") or {}).get("id") == lid] or stats
        g = sum(((x.get("goals") or {}).get("total") or 0) for x in same)
        a = sum(((x.get("goals") or {}).get("assists") or 0) for x in same)
        mins = sum(((x.get("games") or {}).get("minutes") or 0) for x in same)
        pos = next(((x.get("games") or {}).get("position") for x in same if (x.get("games") or {}).get("position")), "") or ""
        return dict(g=g, a=a, min=mins, pos=pos[:1].upper())

    def odds_league(self, lid, season, max_pages=6):
        """Odds pré-jogo dos próximos jogos de uma liga: {fid: {mercado: {...}}}."""
        out, page, total = {}, 1, 1
        while page <= total and page <= max_pages:
            js, hd = http_json(self.BASE + "/odds?" + urllib.parse.urlencode(dict(league=lid, season=season, page=page)), self.h)
            self.calls += 1
            rem = {k.lower(): v for k, v in hd.items()}.get("x-ratelimit-requests-remaining")
            if rem is not None:
                self.remaining = int(rem)
            if js.get("errors"):
                raise ProviderError(json.dumps(js["errors"], ensure_ascii=False))
            for it in js.get("response") or []:
                fid = (it.get("fixture") or {}).get("id")
                if fid:
                    mk = parse_odds(it.get("bookmakers"))
                    if mk:
                        out["af%d" % fid] = mk
            total = int((js.get("paging") or {}).get("total") or 1)
            page += 1
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
    err = SourceFailure(friendly(errs))
    err.key = friendly_key(errs)
    raise err


class SourceFailure(Exception):
    pass


def friendly_key(errs):
    """Código do erro, para o app traduzir a mensagem para o idioma do usuário."""
    raw = " | ".join(errs).lower()
    if not errs:
        return "nokey"
    if "season" in raw or "free plan" in raw:
        return "season"
    if "token" in raw or "application key" in raw or "key" in raw and ("invalid" in raw or "missing" in raw) or "401" in raw or "403" in raw:
        return "badkey"
    if "limit" in raw or "requests" in raw or "429" in raw:
        return "limit"
    if "conex" in raw or "timed out" in raw or "http 5" in raw:
        return "conn"
    return "other"


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


COMPACT_KEYS = ("t", "lg", "h", "a", "res", "p1", "p2", "p3", "btts", "hda", "sc", "sg", "odds", "adj", "mix", "tb", "pos", "hid", "aid")


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
        data.update(error=str(e), error_key=getattr(e, "key", "other"), error_params={}, error_at=now.strftime("%d/%m às %H:%M"))
        data.setdefault("updated", today)
        save(DATA_PATH, data, indent=None)
        log("O site será publicado mesmo assim, mostrando este aviso dentro do app.")
        return
    for k in ("error", "error_at", "error_key", "error_params"):
        data.pop(k, None)
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
        fresh = c and c.get("st", {}).get("v") == 3 and (now - datetime.fromisoformat(c["at"])).total_seconds() < STATS_MAX_AGE_H * 3600
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
            st["rank"] = standings(cur_rows)
            try:  # estatística "times x previsão" (simulação da temporada); nunca derruba a atualização
                data.setdefault("teams", {})[f["lg"]] = {"at": today, "rows": team_table(f["lg"], prev_rows, cur_rows)}
            except Exception as e:  # noqa: BLE001
                log("Aviso: não consegui montar a tabela de times de %s -> %s" % (LEAGUES[f["lg"]]["name"], e))
            st["obs_cur"] = round(sum(r[2] + r[3] for r in cur_rows) / len(cur_rows), 2) if cur_rows else None
            try:  # previsão combinada (experimental); nunca derruba a atualização
                dc = fit_dc(prev_rows + cur_rows, now.isoformat())
                if dc:
                    st["dc"] = dc
            except Exception as e:  # noqa: BLE001
                log("Aviso: sem previsão combinada para %s -> %s" % (LEAGUES[f["lg"]]["name"], e))
        except ProviderError as e:
            log("AVISO: sem estatísticas de %s -> %s" % (LEAGUES[f["lg"]]["name"], e))
            fails.append((LEAGUES[f["lg"]]["name"], str(e)))
            if c and c.get("st", {}).get("v") == 3:
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
            if f.get("hid") and f.get("aid"):   # ids dos times na API-Football: o app mostra os escudos
                m["hid"], m["aid"] = f["hid"], f["aid"]
            if f["res"] is not None:
                m["res"] = f["res"]
            if ko > now and f["lg"] in stats:
                m.update(predict(f["lg"], stats[f["lg"]], f["h"], f["a"])); upd += 1
                mix = predict_mix(f["lg"], stats[f["lg"]], f["h"], f["a"], m)
                if mix:
                    m["mix"] = mix
                else:
                    m.pop("mix", None)
                tb, pos = top_bottom(f["lg"], stats[f["lg"]], f["h"], f["a"])
                m["pos"] = pos
                if tb:
                    m["tb"] = tb
                else:
                    m.pop("tb", None)
    log("Jogos novos: %d · previsões calculadas: %d" % (added, upd))

    # 4) odds das casas (só antes do apito; ficam congeladas depois, como as previsões)
    odds_ok, odds_fail, with_odds = [], [], 0
    if hasattr(prov, "odds_league"):
        upcoming = {}
        for date in new_dates:
            for f in fx[date]:
                if datetime.fromisoformat(f["ko"]) > now and f["res"] is None:
                    upcoming.setdefault((f["lg"], f["lid"], f["season"]), []).append(f["fid"])
        for (lg, lid, season), fids in upcoming.items():
            ck = "odds|%s|%s" % (lg, season)
            c = cache.get(ck)
            if c and (now - datetime.fromisoformat(c["at"])).total_seconds() < ODDS_MAX_AGE_H * 3600:
                book, got = c["odds"], datetime.fromisoformat(c["at"])
            else:
                try:
                    book, got = prov.odds_league(lid, season), now
                    cache[ck] = {"at": now.isoformat(), "odds": book}
                except ProviderError as e:
                    odds_fail.append(LEAGUES[lg]["name"]); log("Aviso: sem odds de %s -> %s" % (LEAGUES[lg]["name"], str(e)[:120]))
                    continue
            odds_ok.append(LEAGUES[lg]["name"])
            for date in new_dates:
                for m in find_day(data, date)["matches"]:
                    if m.get("fid") in book and m.get("ko") and datetime.fromisoformat(m["ko"]) > now:
                        m["odds"] = {"at": got.astimezone(TZ).strftime("%d/%m %H:%M"), "mk": book[m["fid"]]}
                        attach_value(m); with_odds += 1
    for date in new_dates:  # previsões recalculadas -> valor recalculado
        for m in find_day(data, date)["matches"]:
            if m.get("odds") and m.get("ko") and datetime.fromisoformat(m["ko"]) > now:
                attach_value(m)
    log("Odds: %d jogos com odds · ligas: %s" % (with_odds, ", ".join(odds_ok) or "nenhuma"))

    # 5) desfalques (experimental: previsão paralela "com desfalques", medida na aba Acertos)
    with_inj, inj_err = 0, None
    if hasattr(prov, "injuries"):
        up = [m for d in new_dates for m in find_day(data, d)["matches"]
              if str(m.get("fid", "")).startswith("af") and m.get("ko") and datetime.fromisoformat(m["ko"]) > now]
        stale = [m["fid"] for m in up if not (cache.get("inj|" + m["fid"]) and
                 (now - datetime.fromisoformat(cache["inj|" + m["fid"]]["at"])).total_seconds() < INJ_MAX_AGE_H * 3600)]
        try:
            if stale:
                got = prov.injuries(stale)
                for fid, lst in got.items():
                    cache["inj|" + fid] = {"at": now.isoformat(), "list": lst}
        except ProviderError as e:
            inj_err = str(e)[:150]; log("Aviso: sem desfalques -> %s" % inj_err)
        pcalls = 0
        season_of = {f["fid"]: (f["season"], f["lid"]) for d in new_dates for f in fx[d]}
        for m in up:
            ce = cache.get("inj|" + m["fid"])
            if not ce or m["fid"] not in season_of:
                continue
            season, lid = season_of[m["fid"]]
            st = stats.get(m["lg"])
            inj = {"h": [], "a": []}
            for p in ce["list"]:
                side = "h" if sim(p["team"], m.get("hk", m["h"])) >= sim(p["team"], m.get("ak", m["a"])) else "a"
                pk = "pl|%s|%s" % (p["id"], season)
                pc = cache.get(pk)
                if not (pc and (now - datetime.fromisoformat(pc["at"])).days < PLAYER_MAX_AGE_D) and pcalls < PLAYER_CALLS_MAX:
                    try:
                        pc = {"at": now.isoformat(), "s": prov.player_season(p["id"], season, lid)}
                        cache[pk] = pc; pcalls += 1
                    except ProviderError:
                        pc = None
                ps = (pc or {}).get("s") or {}
                tname = m.get("hk", m["h"]) if side == "h" else m.get("ak", m["a"])
                tstats = st["teams"].get(tname, {}).get("c") if st else None
                att, reg = player_importance(ps, tstats)
                inj[side].append(dict(n=p["name"], t="M" if p["type"].lower().startswith("missing") else "Q",
                                      r=p["reason"], pos=ps.get("pos", ""), att=att, reg=reg,
                                      g=ps.get("g", 0), a=ps.get("a", 0)))
            for side in ("h", "a"):
                inj[side].sort(key=lambda x: (-x["att"], not x["reg"]))
            m["inj"] = inj if (inj["h"] or inj["a"]) else None
            adj = injury_adjust(m, m["inj"], st)
            if adj:
                m["adj"] = {k: adj[k] for k in ("lh", "la", "p1", "p2", "p3", "btts", "hda", "sc", "sg")}
            else:
                m.pop("adj", None)
            if m["inj"]:
                with_inj += 1
        log("Desfalques: %d jogos com desfalques · %d consultas de jogadores" % (with_inj, pcalls))

    for d in data["days"]:
        d["matches"] = sorted([m for m in d["matches"] if "p1" in m], key=lambda m: (m.get("t", ""), m["h"]))
    data["days"] = sorted([d for d in data["days"] if d["matches"]], key=lambda d: d["date"])
    archive(data)

    old_t = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    data["teams"] = {k: v for k, v in data.get("teams", {}).items() if v.get("at", "") >= old_t}
    cut = (now - timedelta(days=3)).isoformat()
    cut_prev = (now - timedelta(days=PREV_SEASON_MAX_AGE_D + 5)).isoformat()
    cut_pl = (now - timedelta(days=PLAYER_MAX_AGE_D + 1)).isoformat()
    cache = {k: v for k, v in cache.items()
             if v["at"] >= (cut_prev if k.startswith("prev|") else cut_pl if k.startswith("pl|") else cut)}
    found = {d: len(fx.get(d, [])) for d in new_dates}
    leagues_found = sorted({LEAGUES[f["lg"]]["name"] for d in new_dates for f in fx.get(d, [])})
    data["diag"] = dict(plan=getattr(prov, "plan", None), req=getattr(prov, "req", None),
                        found_today=found[new_dates[0]], found_tomorrow=found[new_dates[1]],
                        leagues_found=leagues_found, leagues_ok=sorted(LEAGUES[k]["name"] for k in stats),
                        leagues_fail=[n for n, _ in fails], fail_reason=friendly([fails[0][1]]) if fails else None,
                        added=added, updated=upd, odds_matches=with_odds, odds_fail=odds_fail,
                        inj_matches=with_inj, inj_error=inj_err)
    # placar ao vivo e notificações: endereço do serviço na Cloudflare (variável LIVE_URL do GitHub)
    data["live_url"] = os.environ.get("LIVE_URL", "").strip().rstrip("/") or None
    for k in ("warning", "warning_key", "warning_params"):
        data.pop(k, None)
    if sum(found.values()) and not stats:
        data["error"] = friendly([fails[0][1]]) if fails else "Os jogos foram encontrados, mas não consegui as estatísticas das competições."
        data["error_key"] = friendly_key([fails[0][1]]) if fails else "other"
        data["error_params"] = {}
        data["error_at"] = now.strftime("%d/%m às %H:%M")
    elif fails:
        names = ", ".join(n for n, _ in fails[:6])
        data["warning"] = "%d competição(ões) ficaram sem previsão: %s. Motivo: %s" % (len(fails), names, friendly([fails[0][1]]))
        data["warning_key"], data["warning_params"] = "partial", {"n": len(fails), "list": names}
    elif not sum(found.values()):
        data["warning"] = ("A API respondeu, mas não trouxe nenhum jogo das competições acompanhadas para hoje e amanhã. "
                           "Se isso se repetir em dias com rodada, o plano da API pode estar limitando as datas.")
        data["warning_key"], data["warning_params"] = "nogames", {}
    data.update(updated=today, updated_time=now.strftime("%H:%M"), source=prov.name,
                quota=prov.remaining, version=2)
    save(DATA_PATH, data, indent=None)
    save(CACHE_PATH, cache)
    log("Requisições usadas: %d%s" % (prov.calls, "" if prov.remaining is None else " · restantes hoje: %d" % prov.remaining))


if __name__ == "__main__":
    main()
