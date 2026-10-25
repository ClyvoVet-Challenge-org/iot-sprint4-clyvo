"""Vigia B: referências e cálculo das 10 correlações."""

import csv
import os
from pathlib import Path

import numpy as np

DIAS_ANALISADOS = 30 
MIN_DIAS = 10  

# Limites para considerar um sinal do sensor alterado
LIMITE_3DIAS = 0.25 
LIMITE_14DIAS = 0.20 


# ============================================================================
#  REFERÊNCIAS
# ============================================================================

def _pasta_referencias():
    """Localiza a pasta referencias/."""
    pasta_vigia_b = Path(__file__).resolve().parent
    for onde_procurar in (pasta_vigia_b, pasta_vigia_b.parent, pasta_vigia_b.parent.parent):
        for pasta_ref in (onde_procurar / "referencias", onde_procurar / "dados" / "referencias"):
            if (pasta_ref / "ref_peso.csv").exists():
                return pasta_ref
    if (pasta_vigia_b / "ref_peso.csv").exists():
        return pasta_vigia_b
    raise FileNotFoundError("Planilhas de referência (pasta referencias/) não encontradas.")


def _ler_csv(nome):
    with open(_pasta_referencias() / nome, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v):
    """Transforma em número float."""
    return None if v is None or str(v).strip() == "" else float(v)


def _linhas_das_planilhas():
    """Lê as referências das planilhas, traduz a planilha para o banco."""
    sinal = {"aumenta": 1, "diminui": -1, "": 0}
    peso = [(r["especie"], r["raca"], {"Ambos": "A"}.get(r["sexo"], r["sexo"]), float(r["peso_min_kg"]),
             float(r["peso_max_kg"]), int(r["idade_adulta_meses"])) for r in _ler_csv("ref_peso.csv")]
    cron = {(r["doenca"], r["especie"]): r for r in _ler_csv("ref_doencas.csv")}
    doencas = []
    for c in _ler_csv("catalogo_doencas.csv"):
        r = cron.get((c["doenca"], c["especie"]), {})
        doencas.append((c["doenca"], c["especie"], "CRONICA" if c["tipo"].startswith("cronica") else "INFECCIOSA",
                        c["monitora_surto"], _num(r.get("idade_risco_anos")),
                        sinal[r.get("comida", "") or ""], sinal[r.get("agua", "") or ""],
                        sinal[r.get("movimento", "") or ""], (r.get("momento_sinal") or "").upper()))
    predisp = [(p["especie"], p["raca"], p["doenca"], p["tipo"].upper(), _num(p["razao_risco"]), p["medida"])
               for p in _ler_csv("ref_predisposicao.csv")]
    vacinas = [(v["vacina"], v["doenca"], v["especie"], v["cobertura"]) for v in _ler_csv("ref_vacinas.csv")]
    consumo = [(c["especie"], c["castrado"], float(c["coef_rer"]), float(c["expoente"]),
                float(c["fator_manutencao"]), float(c["coef_agua_ml"]), float(c["tolerancia"]))
               for c in _ler_csv("ref_consumo.csv")]
    racoes = [(r["especie"], float(r["kcal_kg"])) for r in _ler_csv("ref_racoes.csv")]
    return peso, doencas, predisp, vacinas, consumo, racoes


def _linhas_do_banco(con):
    """Lê as referências do banco, no mesmo formato das planilhas."""
    cur = con.cursor()

    def q(sql):
        cur.execute(sql)
        return [tuple(l) for l in cur.fetchall()]

    peso = [(e, r, s, float(mn), float(mx), int(ia)) for e, r, s, mn, mx, ia in
            q("SELECT especie_animal, raca_animal, sexo_animal, peso_min_kg, peso_max_kg, idade_adulta_meses "
              "FROM T_CLYVO_REF_PESO_RACA")]
    doencas = [(n, e, t, m, _num(i), int(sc or 0), int(sa or 0), int(sm or 0), ms or "") for n, e, t, m, i, sc, sa, sm, ms in
               q("SELECT nm_doenca, especie_alvo, tp_doenca, monitora_surto, idade_risco_anos, sinal_comida, "
                 "sinal_agua, sinal_movimento, momento_sinal FROM T_CLYVO_DOENCA")]
    predisp = [(e, r, d, t, _num(o), m or "") for e, r, d, t, o, m in
               q("SELECT p.especie_animal, p.raca_animal, d.nm_doenca, p.tp_relacao, p.vl_razao_risco, p.ds_medida "
                 "FROM T_CLYVO_PREDISP_RACA p JOIN T_CLYVO_DOENCA d ON d.id_doenca = p.id_doenca")]
    vacinas = q("SELECT v.nm_vacina, d.nm_doenca, d.especie_alvo, vd.ds_cobertura FROM T_CLYVO_VACINA_DOENCA vd "
                "JOIN T_CLYVO_VACINA v ON v.id_vacina = vd.id_vacina JOIN T_CLYVO_DOENCA d ON d.id_doenca = vd.id_doenca")
    consumo = [(e, c, *map(float, resto)) for e, c, *resto in
               q("SELECT especie_animal, castrado, coef_rer, expoente, fator_manutencao, coef_agua_ml, tolerancia "
                 "FROM T_CLYVO_REF_CONSUMO")]
    racoes = [(e, float(k)) for e, k in q("SELECT especie_animal, kcal_kg FROM T_CLYVO_REF_RACAO")]
    return peso, doencas, predisp, vacinas, consumo, racoes


def _montar(peso, doencas, predisp, vacinas, consumo, racoes, origem):
    """Transforma as 6 listas soltas em dicionário."""
    ref = {"origem": origem}
    ref["peso"] = {(e, r, s): (mn, mx) for e, r, s, mn, mx, _ in peso}
    ref["racas"] = sorted({(e, r) for e, r, _, _, _, _ in peso})
    ref["idade_adulta"] = {}
    for e, r, _, _, _, meses in peso:
        ref["idade_adulta"][(e, r)] = max(meses / 12, ref["idade_adulta"].get((e, r), 0))
    ref["cronicas"] = {}
    for nome, esp, tipo, monitora, idade, sc, sa, sm, momento in doencas:
        if tipo == "CRONICA":
            ref["cronicas"][(nome, esp)] = {"idade_risco": idade, "tardio": momento == "TARDIO",
                                            "sinais": {"comida": sc, "agua": sa, "movimento": sm}}
    ref["predisp"] = {}
    for esp, raca, doenca, tipo, razao, medida in predisp:
        ref["predisp"].setdefault((esp, raca), []).append(
            {"doenca": doenca, "tipo": tipo, "razao_risco": razao, "medida": medida,
             # forte: razão de risco >= 2 ou mutação genética
             "forte": tipo == "PREDISPOSICAO" and (razao is None or razao >= 2)})
    ref["vacina_previne"] = {}
    for vacina, doenca, esp, cobertura in vacinas:
        ref["vacina_previne"].setdefault(vacina, {})[(doenca, esp)] = "parcial" if cobertura.startswith("parcial") else "total"
    ref["consumo"] = {(e, c): {"coef_rer": a, "expoente": b, "fator": f, "coef_agua": ag, "tolerancia": t}
                      for e, c, a, b, f, ag, t in consumo}
    ref["racoes_kcal"] = {e: sorted(k for esp, k in racoes if esp == e) for e in {e for e, _ in racoes}}
    ref["kcal_media"] = {e: float(np.mean(v)) for e, v in ref["racoes_kcal"].items()}
    return ref


def carregar_referencias(con=None):
    """Carrega as referências do banco (Oracle) ou, sem conexão, das planilhas."""
    if con is not None:
        return _montar(*_linhas_do_banco(con), origem="banco")
    user, pwd, dsn = (os.getenv("CLYVO_DB_USER"), os.getenv("CLYVO_DB_PASSWORD"), os.getenv("CLYVO_DB_DSN"))
    if user and pwd and dsn:
        try:
            import oracledb
            with oracledb.connect(user=user, password=pwd, dsn=dsn) as conexao:
                return _montar(*_linhas_do_banco(conexao), origem="Oracle")
        except Exception as erro: 
            print(f"Não foi possível ler as referências do Oracle ({erro}). Usando as planilhas.")
    return _montar(*_linhas_das_planilhas(), origem=f"planilhas ({_pasta_referencias().name}/)")


# ============================================================================
#  QUEM O VIGIA B AVALIA
# ============================================================================

def idade_adulta(especie, raca, ref):
    """Idade adulta da raça, em anos (da tabela de referência)."""
    return ref["idade_adulta"][(especie, raca)]


def avaliado_pelo_vigia_b(especie, raca, idade, ref):
    """Adultos das raças com referência de peso."""
    return (especie, raca) in ref["racas"] and idade >= idade_adulta(especie, raca, ref)


def faixa_peso(especie, raca, sexo, ref):
    """Faixa de peso ideal da raça (e do sexo, nos gatos)."""
    return ref["peso"].get((especie, raca, sexo)) or ref["peso"][(especie, raca, "A")]


# ============================================================================
#  CORRELAÇÃO 2 — CONSUMO ESPERADO
# ============================================================================

def consumo_esperado(especie, raca, sexo, peso, castrado, kcal_kg_racao, ref):
    """Calcula comida (g/dia) e água (ml/dia) esperadas."""
    pmin, pmax = faixa_peso(especie, raca, sexo, ref)
    p = min(max(peso, pmin), pmax)
    c = ref["consumo"][(especie, "S" if castrado else "N")]
    kcal_dia = c["coef_rer"] * p ** c["expoente"] * c["fator"]
    usou_media = not kcal_kg_racao
    kcal_kg = ref["kcal_media"][especie] if usou_media else float(kcal_kg_racao)
    return kcal_dia / kcal_kg * 1000, c["coef_agua"] * p ** c["expoente"], c["tolerancia"], usou_media


# ============================================================================
#  EXTRAÇÃO DE FEATURES (as 10 correlações do Vigia B)
# ============================================================================

# Campos numéricos das fichas
FEATURES_NUMERICAS = [
    "idade_anos", "peso_kg", "castrado",
    "desvio_peso",                              
    "castrado_perto_limite",                        
    "comida_vs_esperado", "agua_vs_esperado",       
    "comida_vs_baseline", "agua_vs_baseline", "mov_vs_baseline",   
    "peso_x_comida",                                 
    "tend_comida", "tend_agua", "tend_mov",          
    "idade_risco",                                   
    "predisp_sinal_alterado", "predisp_forte", "sinal_tardio",     
    "vacinas_atrasadas", "vacina_doenca_regional",   
    "dias_sem_consulta",                             
    "alerta_regional",                               
]

# Campos de texto da ficha, que viram colunas 0/1
FEATURES_CATEGORICAS = ["especie", "raca"]

# Texto de cada sinal do sensor no alerta, sendo +1 aumento, -1 diminuiu
NOME_SINAL = {("comida", 1): "comendo mais", ("comida", -1): "comendo menos",
              ("agua", 1): "bebendo mais água", ("agua", -1): "bebendo menos água",
              ("movimento", 1): "mais agitado", ("movimento", -1): "menos ativo"}


def _tendencia(valores_sensor):
    """Tendência dos valores captados pelo sensor nos 14 dias."""
    valores_sensor = np.asarray(valores_sensor, dtype=float)
    if len(valores_sensor) < 3 or valores_sensor.mean() <= 0:
        return 0.0
    dias = np.arange(len(valores_sensor))
    inclinacao = np.polyfit(dias, valores_sensor, 1)[0]
    return float(inclinacao * (len(valores_sensor) - 1) / valores_sensor.mean())


def _razao(a, b):
    """Valor dividido pela referência (1.0 = igual; 1.4 = 40% a mais)."""
    return float(a / b) if b > 0 else 1.0


def _sinais_alterados(f, tolerancia):
    """Direção de cada sinal: +1 aumentou, -1 diminuiu, 0 normal."""
    def avaliar_sinal(vs_esperado, vs_base, tend):
        sobe = (vs_esperado is not None and vs_esperado > 1 + tolerancia) or vs_base > 1 + LIMITE_3DIAS \
            or tend > LIMITE_14DIAS
        desce = (vs_esperado is not None and vs_esperado < 1 - tolerancia) or vs_base < 1 - LIMITE_3DIAS \
            or tend < -LIMITE_14DIAS
        return 1 if sobe and not desce else -1 if desce and not sobe else 0

    return {"comida": avaliar_sinal(f["comida_vs_esperado"], f["comida_vs_baseline"], f["tend_comida"]),
            "agua": avaliar_sinal(f["agua_vs_esperado"], f["agua_vs_baseline"], f["tend_agua"]),
            "movimento": avaliar_sinal(None, f["mov_vs_baseline"], f["tend_mov"])}


def _combina(doenca, sinais_doenca, sinais, desvio_peso):
    """Quantos sinais da doença combinam com os do sensor (0 = não combina)."""
    if doenca == "Obesidade" and desvio_peso <= 0:
        return 0
    certos = 0
    for chave, esperado in sinais_doenca.items():
        if esperado == 0:
            continue
        if sinais[chave] == esperado:
            certos += 1
        elif sinais[chave] == -esperado:
            return 0
    return certos


def extrair_features(animal, leituras, vacinas_atrasadas, dias_sem_consulta, doencas_regionais, ref):
    """Calcula as features de um animal. Retorna (features, detalhes)."""
    esp, raca, sexo = animal["especie"], animal["raca"], animal["sexo"]
    idade, peso, castrado = float(animal["idade_anos"]), float(animal["peso_kg"]), bool(animal["castrado"])
    leituras = list(leituras)[-DIAS_ANALISADOS:]
    if len(leituras) < MIN_DIAS:
        raise ValueError(f"São necessárias pelo menos {MIN_DIAS} leituras diárias.")
    pmin, pmax = faixa_peso(esp, raca, sexo, ref)

    comida = np.array([l["comida"] for l in leituras], dtype=float)
    agua = np.array([l["agua"] for l in leituras], dtype=float)
    mov = np.array([l["movimento"] for l in leituras], dtype=float)

    # Correlação 1: peso x faixa ideal
    if peso > pmax:
        desvio_peso = (peso - pmax) / pmax
    elif peso < pmin:
        desvio_peso = (peso - pmin) / pmin
    else:
        desvio_peso = 0.0

    # Correlação 10: castrado e perto do limite de peso
    castrado_perto_limite = int(castrado and peso > 0.9 * pmax)

    # Correlação 2: consumo x esperado (últimos 7 dias)
    esp_comida, esp_agua, tolerancia, usou_media = consumo_esperado(esp, raca, sexo, peso, castrado,
                                                                    animal.get("kcal_kg_racao"), ref)
    comida_vs_esperado = _razao(comida[-7:].mean(), esp_comida)
    agua_vs_esperado = _razao(agua[-7:].mean(), esp_agua)

    # Correlação 3: últimos 3 dias x média do animal
    base = slice(0, max(len(leituras) - 7, 3))
    comida_vs_baseline = _razao(comida[-3:].mean(), comida[base].mean())
    agua_vs_baseline = _razao(agua[-3:].mean(), agua[base].mean())
    mov_vs_baseline = _razao(mov[-3:].mean(), mov[base].mean())

    # Correlação 4: peso x consumo
    if desvio_peso > 0 and comida_vs_esperado > 1.10:
        peso_x_comida = 1
    elif desvio_peso < 0 and comida_vs_esperado < 0.90:
        peso_x_comida = -1
    else:
        peso_x_comida = 0

    # Correlação 5: tendência em 14 dias
    tend_comida, tend_agua, tend_mov = _tendencia(comida[-14:]), _tendencia(agua[-14:]), _tendencia(mov[-14:])

    parcial = {"comida_vs_esperado": comida_vs_esperado, "agua_vs_esperado": agua_vs_esperado,
               "comida_vs_baseline": comida_vs_baseline, "agua_vs_baseline": agua_vs_baseline,
               "mov_vs_baseline": mov_vs_baseline, "tend_comida": tend_comida, "tend_agua": tend_agua,
               "tend_mov": tend_mov}
    sinais = _sinais_alterados(parcial, tolerancia)

    # Correlações 6 e 7: raça x idade de risco x sinal do sensor
    relacoes = {p["doenca"]: p for p in ref["predisp"].get((esp, raca), [])}
    protegidas = [d for d, p in relacoes.items() if p["tipo"] == "PROTECAO"]
    em_risco, compativeis = [], []
    for (doenca, e), info in ref["cronicas"].items():
        if e != esp or info["idade_risco"] is None or idade < info["idade_risco"]:
            continue
        rel = relacoes.get(doenca)
        n_sinais = _combina(doenca, info["sinais"], sinais, desvio_peso)
        item = {"doenca": doenca, "sinais": n_sinais, "tardio": info["tardio"],
                "razao_risco": rel["razao_risco"] if rel else None, "forte": bool(rel and rel["forte"]),
                "predisposicao": bool(rel and rel["tipo"] == "PREDISPOSICAO"),
                "medida": rel["medida"] if rel else ""}
        if item["predisposicao"]:
            em_risco.append(item)
        if n_sinais > 0 and doenca not in protegidas:
            compativeis.append(item)
    # Ordena da causa mais provável para a menos provável
    compativeis.sort(key=lambda i: (i["predisposicao"], i["sinais"], i["forte"], i["razao_risco"] or 0), reverse=True)
    confirmadas = [i for i in compativeis if i["predisposicao"]]
    principal = confirmadas[0] if confirmadas else None

    # Correlação 8: vacina atrasada para doença em surto no bairro
    desprotegidas = {}
    for v in vacinas_atrasadas:
        for (doenca, e), cobertura in ref["vacina_previne"].get(v, {}).items():
            if e == esp and desprotegidas.get(doenca) != "total":
                desprotegidas[doenca] = cobertura
    vacina_doenca_regional = {d: desprotegidas[d] for d in doencas_regionais if d in desprotegidas}

    features = {
        "especie": esp,
        "raca": raca,
        "idade_anos": round(idade, 2),
        "peso_kg": round(peso, 2),
        "castrado": int(castrado),
        "desvio_peso": round(desvio_peso, 4),
        "castrado_perto_limite": castrado_perto_limite,
        "comida_vs_esperado": round(comida_vs_esperado, 4),
        "agua_vs_esperado": round(agua_vs_esperado, 4),
        "comida_vs_baseline": round(comida_vs_baseline, 4),
        "agua_vs_baseline": round(agua_vs_baseline, 4),
        "mov_vs_baseline": round(mov_vs_baseline, 4),
        "peso_x_comida": peso_x_comida,
        "tend_comida": round(tend_comida, 4),
        "tend_agua": round(tend_agua, 4),
        "tend_mov": round(tend_mov, 4),
        "idade_risco": int(len(em_risco) > 0),
        "predisp_sinal_alterado": int(principal is not None),
        "predisp_forte": int(bool(principal and principal["forte"])),
        "sinal_tardio": int(bool(principal and principal["tardio"])),
        "vacinas_atrasadas": len(vacinas_atrasadas),
        "vacina_doenca_regional": int(len(vacina_doenca_regional) > 0),
        "dias_sem_consulta": int(dias_sem_consulta),
        "alerta_regional": int(len(doencas_regionais) > 0),
    }
    detalhes = {
        "faixa_peso": (pmin, pmax),
        "consumo_esperado_comida_g": round(esp_comida, 1),
        "consumo_esperado_agua_ml": round(esp_agua, 1),
        "usou_media_racao": usou_media,
        "tolerancia": tolerancia,
        "sinais": sinais,
        "doencas_idade_risco": [i["doenca"] for i in em_risco],
        "protecoes": protegidas,
        "causas_compativeis": compativeis,
        "vacinas_atrasadas": list(vacinas_atrasadas),
        "doencas_regionais": list(doencas_regionais),
        "doencas_regionais_sem_vacina": vacina_doenca_regional,
    }
    return features, detalhes


# ============================================================================
#  CAUSA MAIS PROVÁVEL
# ============================================================================

def causa_provavel(features, detalhes):
    """Texto com a causa mais provável do alerta."""
    alterados = [NOME_SINAL[(k, v)] for k, v in detalhes["sinais"].items() if v != 0]
    predispostas = [c for c in detalhes["causas_compativeis"] if c["predisposicao"]]
    if predispostas:
        c = predispostas[0]
        rr = f"{c['razao_risco']:.1f}".replace(".", ",") + "× mais comum na raça" if c["razao_risco"] else \
            "predisposição genética da raça"
        return f"{c['doenca']} ({rr})"
    if detalhes["doencas_regionais_sem_vacina"]:
        doencas = " e ".join(d.lower() for d in detalhes["doencas_regionais_sem_vacina"])
        texto = f"Risco de {doencas}: surto no bairro e vacina atrasada"
        return texto + (" (" + ", ".join(alterados) + ")" if alterados else "")
    if features["peso_x_comida"] == 1 or features["desvio_peso"] > 0.05:
        return "Sobrepeso"
    if features["desvio_peso"] < -0.10:
        return "Baixo peso"
    if alterados:
        return "Mudança de comportamento: " + ", ".join(alterados)
    return "Nenhuma alteração relevante"


# ============================================================================
#  PONTUAÇÃO DE RISCO
# ============================================================================

def pontuar_risco(f):
    """Calcula a pontuação de risco. Retorna (pontos, suspeita_principal)."""
    pontos, suspeitas = 0.0, []

    # Peso (correlações 1, 4 e 10)
    if f["desvio_peso"] > 0.15:
        pontos += 3; suspeitas.append("obesidade")
    elif f["desvio_peso"] > 0.05:
        pontos += 2; suspeitas.append("sobrepeso")
    elif f["desvio_peso"] < -0.10:
        pontos += 2; suspeitas.append("baixo peso")
    if f["peso_x_comida"] == 1:
        pontos += 2; suspeitas.append("obesidade")
    elif f["peso_x_comida"] == -1:
        pontos += 2; suspeitas.append("desnutricao")
    if f["castrado_perto_limite"]:
        pontos += 1

    # Consumo x esperado (correlação 2)
    if f["agua_vs_esperado"] > 1.30:
        pontos += 1.5; suspeitas.append("sede excessiva")
    if f["comida_vs_esperado"] < 0.70:
        pontos += 1.5; suspeitas.append("perda de apetite")

    # Consumo x média do animal (correlação 3)
    if f["comida_vs_baseline"] < 0.70:
        pontos += 3; suspeitas.append("perda de apetite")
    elif f["comida_vs_baseline"] < 0.85:
        pontos += 1
    elif f["comida_vs_baseline"] > 1.30:
        pontos += 1.5; suspeitas.append("apetite aumentado")
    if f["agua_vs_baseline"] > 1.30:
        pontos += 2; suspeitas.append("sede excessiva")
    elif f["agua_vs_baseline"] < 0.70:
        pontos += 2; suspeitas.append("baixa ingestao de agua")
    if f["mov_vs_baseline"] < 0.70:
        pontos += 2; suspeitas.append("queda de atividade")

    # Tendência (correlação 5)
    if f["tend_comida"] < -0.25:
        pontos += 2; suspeitas.append("perda de apetite")
    if f["tend_agua"] > 0.25:
        pontos += 2; suspeitas.append("sede excessiva")
    if f["tend_mov"] < -0.25:
        pontos += 2; suspeitas.append("queda de atividade")

    # Predisposição da raça com o sinal certo (correlações 6 e 7)
    if f["predisp_sinal_alterado"]:
        extra = 3.0 if f["predisp_forte"] else 2.0
        if f["sinal_tardio"]:
            extra /= 2
        pontos += extra; suspeitas.insert(0, "predisposicao confirmada")
    elif f["idade_risco"]:
        pontos += 0.5

    # Vacinas, surto no bairro e consultas (correlações 8 e 9)
    tem_sinal = pontos >= 2
    if f["vacina_doenca_regional"]:
        pontos += 2.5; suspeitas.append("vacina atrasada para doenca em surto na regiao")
    elif f["vacinas_atrasadas"] > 0:
        pontos += 0.5
    if f["alerta_regional"] and (tem_sinal or f["comida_vs_baseline"] < 0.90 or f["mov_vs_baseline"] < 0.90):
        pontos += 1.5; suspeitas.append("risco regional")
    if f["dias_sem_consulta"] > 365:
        pontos += 1.0 if tem_sinal else 0.5

    return pontos, (suspeitas[0] if suspeitas else "nenhuma")


def nivel_por_pontos(pontos):
    """Converte a pontuação em nível de risco."""
    if pontos >= 6:
        return "ALTO"
    if pontos >= 3:
        return "MEDIO"
    return "BAIXO"
