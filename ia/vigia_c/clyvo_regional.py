"""Vigia C: alerta regional (correlações 11 a 14)."""

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

JANELA_DIAS = 14  
MIN_JANELAS_HISTORICO = 12  
DATA_REFERENCIA = date(2026, 10, 4) 


LIMIAR = {
    "S": {"z": 2.0, "casos_min": 2},  # contagiosa
    "N": {"z": 3.0, "casos_min": 4},  # não contagiosa
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]

CONSULTA_CASOS = """
SELECT c.dt_consulta,
       e.cidade,
       e.bairro,
       a.especie_animal,
       d.nm_doenca,
       d.especie_alvo,
       d.contagiosa,
       d.monitora_surto,
       d.alerta_caso_unico,
       d.mes_inicio_pico,
       d.mes_fim_pico
  FROM T_CLYVO_CONSULTA_DOENCA cd
  JOIN T_CLYVO_CONSULTA        c ON c.id_consulta = cd.id_consulta
  JOIN T_CLYVO_DOENCA          d ON d.id_doenca   = cd.id_doenca
  JOIN T_CLYVO_ANIMAL          a ON a.id_animal   = c.id_animal
  JOIN T_CLYVO_ENDERECO_ANIMAL e ON e.id_animal   = a.id_animal
 WHERE c.st_consulta = 'PASSADA'
   AND d.tp_doenca = 'INFECCIOSA'
"""


# ============================================================================
#  CARREGAMENTO DOS DADOS
# ============================================================================

def carregar_casos(caminho_csv="casos_vigia_c.csv", con=None):
    """Carrega os diagnósticos do banco (Oracle) ou do CSV."""
    origem = None
    if con is not None:
        casos, origem = pd.read_sql(CONSULTA_CASOS, con), "banco"
    else:
        user, pwd, dsn = (os.getenv("CLYVO_DB_USER"), os.getenv("CLYVO_DB_PASSWORD"), os.getenv("CLYVO_DB_DSN"))
        if user and pwd and dsn:
            try:
                import oracledb
                with oracledb.connect(user=user, password=pwd, dsn=dsn) as conexao:
                    casos, origem = pd.read_sql(CONSULTA_CASOS, conexao), "Oracle"
            except Exception as erro:
                print(f"Não foi possível ler do Oracle ({erro}). Usando o CSV.")
        if origem is None:
            casos, origem = pd.read_csv(caminho_csv), "CSV"
    casos.columns = [c.lower() for c in casos.columns]
    casos["dt_consulta"] = pd.to_datetime(casos["dt_consulta"]).dt.date
    return casos, origem


# ============================================================================
#  CORRELAÇÕES 11 e 13 — casos por bairro, doença e espécie, por janela de tempo
# ============================================================================

def filtrar_especie_alvo(casos):
    """Correlação 13: mantém só os casos da espécie-alvo da doença."""
    return casos[casos["especie_alvo"] == casos["especie_animal"]].copy()


def montar_janelas(casos, hoje=DATA_REFERENCIA, janela_dias=JANELA_DIAS):
    """Conta os casos por bairro, doença, espécie e janela (0 = atual)."""
    casos = filtrar_especie_alvo(casos)
    casos = casos[(casos["monitora_surto"] == "S") & (casos["dt_consulta"] <= hoje)].copy()
    casos["janela"] = [(hoje - d).days // janela_dias for d in casos["dt_consulta"]]
    n_janelas = int(casos["janela"].max()) + 1

    info_doenca = (casos[["nm_doenca", "contagiosa", "mes_inicio_pico", "mes_fim_pico"]]
                   .drop_duplicates("nm_doenca").set_index("nm_doenca"))
    grupos = casos[["cidade", "bairro", "nm_doenca", "especie_animal"]].drop_duplicates()

    contagem = casos.groupby(["cidade", "bairro", "nm_doenca", "especie_animal", "janela"]).size()
    linhas = []
    for g in grupos.itertuples(index=False):
        for j in range(n_janelas):
            fim = hoje - timedelta(days=j * janela_dias)
            linhas.append({"cidade": g.cidade, "bairro": g.bairro, "doenca": g.nm_doenca,
                           "especie": g.especie_animal, "janela": j,
                           "inicio": fim - timedelta(days=janela_dias - 1), "fim": fim,
                           "casos": int(contagem.get((g.cidade, g.bairro, g.nm_doenca, g.especie_animal, j), 0))})
    tabela = pd.DataFrame(linhas)
    return tabela.join(info_doenca, on="doenca")


# ============================================================================
#  CORRELAÇÃO 12 — época de pico
# ============================================================================

def em_pico(mes, inicio, fim):
    """Verifica se o mês está na época de pico."""
    if pd.isna(inicio) or pd.isna(fim):
        return False
    inicio, fim = int(inicio), int(fim)
    return inicio <= mes <= fim if inicio <= fim else (mes >= inicio or mes <= fim)


def texto_pico(inicio, fim):
    """Texto da época de pico (ex: outubro a março)."""
    return f"{MESES[int(inicio) - 1]} a {MESES[int(fim) - 1]}"


# ============================================================================
#  Z-SCORE
# ============================================================================

def calcular_estatisticas(tabela):
    """Calcula média histórica, desvio, z-score e época de pico de cada janela."""
    tabela = tabela.sort_values(["bairro", "doenca", "especie", "janela"], ascending=[True, True, True, False]).copy()
    medias, desvios = [], []
    for _, grupo in tabela.groupby(["bairro", "doenca", "especie"], sort=False):
        valores = grupo["casos"].to_numpy()
        for i in range(len(valores)):
            historico = valores[:i]                       # janelas anteriores
            medias.append(historico.mean() if len(historico) else np.nan)
            desvios.append(historico.std() if len(historico) else np.nan)
    tabela["media_hist"] = medias
    tabela["desvio_hist"] = desvios
    desvio_ajustado = np.maximum.reduce([tabela["desvio_hist"].fillna(0),
                                         np.sqrt(tabela["media_hist"].fillna(0)),
                                         np.full(len(tabela), 0.5)])
    tabela["z"] = (tabela["casos"] - tabela["media_hist"].fillna(0)) / desvio_ajustado
    tabela["em_pico"] = [em_pico(f.month, i, e) for f, i, e in
                         zip(tabela["fim"], tabela["mes_inicio_pico"], tabela["mes_fim_pico"])]
    return tabela.sort_values(["bairro", "doenca", "especie", "janela"]).reset_index(drop=True)


# ============================================================================
#  REGRA DE ALERTA (correlações 11, 12 e 14)
# ============================================================================

def classificar_alerta(linha):
    """Define o nível do alerta da janela. Retorna (nivel ou None, motivo)."""
    limiar = LIMIAR[linha["contagiosa"]]
    esperado = linha["media_hist"] if not pd.isna(linha["media_hist"]) else 0.0
    texto_esperado = f"média histórica de {esperado:.1f}".replace(".", ",") + f" caso(s) a cada {JANELA_DIAS} dias"

    # Surto (correlações 11 e 14)
    if linha["casos"] >= limiar["casos_min"] and linha["z"] >= limiar["z"]:
        nivel = "ALTO" if (linha["z"] >= limiar["z"] * 2 or linha["casos"] >= 2 * limiar["casos_min"] + 2) else "MEDIO"
        tipo = "doença contagiosa" if linha["contagiosa"] == "S" else "doença não contagiosa"
        motivo = (f"{linha['casos']} casos de {linha['doenca']} em {linha['bairro']} nos últimos {JANELA_DIAS} dias "
                  f"({texto_esperado}; {tipo}).")
        if linha["em_pico"]:
            motivo += f" Época de maior incidência ({texto_pico(linha['mes_inicio_pico'], linha['mes_fim_pico'])})."
        return nivel, motivo

    # Época de pico (correlação 12)
    if linha["em_pico"] and linha["casos"] >= 1:
        motivo = (f"{linha['casos']} caso(s) de {linha['doenca']} em {linha['bairro']} durante a época de "
                  f"maior incidência ({texto_pico(linha['mes_inicio_pico'], linha['mes_fim_pico'])}). Alerta preventivo.")
        return "BAIXO", motivo

    return None, ""


def historico_suficiente(tabela):
    """Janelas com histórico suficiente."""
    return tabela["janela"] <= tabela["janela"].max() - MIN_JANELAS_HISTORICO


def gerar_alertas_regionais(tabela, janela=0):
    """Alertas de uma janela (0 = atual)."""
    atual = tabela[(tabela["janela"] == janela) & historico_suficiente(tabela)].copy()
    if atual.empty:
        return atual.assign(nivel_risco=pd.Series(dtype=str), motivo=pd.Series(dtype=str))
    resultado = atual.apply(classificar_alerta, axis=1, result_type="expand")
    atual["nivel_risco"], atual["motivo"] = resultado[0], resultado[1]
    alertas = atual[atual["nivel_risco"].notna()].copy()
    ordem = {"ALTO": 0, "MEDIO": 1, "BAIXO": 2}
    alertas["_ordem"] = alertas["nivel_risco"].map(ordem)
    return alertas.sort_values(["_ordem", "z"], ascending=[True, False]).drop(columns="_ordem")


# ============================================================================
#  CASO ÚNICO (raiva)
# ============================================================================

def alertas_caso_unico(casos, hoje=DATA_REFERENCIA, janela_dias=JANELA_DIAS):
    """Raiva: 1 caso suspeito gera alerta ALTO para todas as espécies do bairro."""
    casos = filtrar_especie_alvo(casos)
    inicio = hoje - timedelta(days=janela_dias - 1)
    recentes = casos[(casos["alerta_caso_unico"] == "S") & (casos["dt_consulta"] >= inicio) &
                     (casos["dt_consulta"] <= hoje)]
    especies = sorted(casos["especie_animal"].unique())
    linhas = []
    for (cidade, bairro, doenca), grupo in recentes.groupby(["cidade", "bairro", "nm_doenca"]):
        quem = ", ".join(f"{n} {'cão' if e == 'Canina' else 'gato'}{'s' if n > 1 else ''}"
                         for e, n in grupo["especie_animal"].value_counts().items())
        motivo = (f"Suspeita de {doenca.lower()} em {bairro} ({quem}, nos últimos {janela_dias} dias). Alerta imediato: "
                  f"doença fatal, transmissível a humanos e de notificação obrigatória.")
        for especie in especies:
            linhas.append({"cidade": cidade, "bairro": bairro, "doenca": doenca, "especie": especie, "janela": 0,
                           "inicio": inicio, "fim": hoje, "casos": len(grupo), "media_hist": np.nan, "z": np.nan,
                           "em_pico": False, "nivel_risco": "ALTO", "motivo": motivo, "caso_unico": True})
    return pd.DataFrame(linhas)


def recomendacao(nivel, doenca, especie, caso_unico=False):
    """Texto de recomendação do alerta."""
    publico = "cães" if especie == "Canina" else "gatos"
    nome = doenca.lower()
    if caso_unico:
        return (f"Confira se a vacina antirrábica dos {publico} está em dia, evite contato com animais desconhecidos "
                f"e procure o veterinário ou a vigilância em saúde em caso de mordida.")
    if nivel == "ALTO":
        return (f"Surto provável de {nome}. Confira a vacinação dos {publico} da região, evite contato com animais "
                f"doentes e procure o veterinário aos primeiros sintomas.")
    if nivel == "MEDIO":
        return f"Aumento de casos de {nome}. Confira a vacinação e observe sintomas nos {publico}."
    return f"Época de maior incidência de {nome}. Mantenha a vacinação dos {publico} em dia."


# ============================================================================
#  ISOLATION FOREST
# ============================================================================

FEATURES_IF = ["casos", "media_hist", "z", "contagiosa_num", "em_pico_num"]


def preparar_features_if(tabela):
    """Monta as colunas do Isolation Forest."""
    t = tabela[historico_suficiente(tabela)].copy()
    t["em_pico_num"] = t["em_pico"].astype(int)
    t["contagiosa_num"] = (t["contagiosa"] == "S").astype(int)
    return t


def treinar_isolation_forest(tabela, contaminacao=0.005, semente=42):
    """Treina o Isolation Forest só com as janelas do histórico (o passado define o normal)."""
    from sklearn.ensemble import IsolationForest
    t = preparar_features_if(tabela)
    historico = t[t["janela"] > 0]
    modelo = IsolationForest(n_estimators=200, max_samples=1.0, contamination=contaminacao, random_state=semente)
    return modelo.fit(historico[FEATURES_IF])


def marcar_anomalias(tabela, modelo):
    """Avalia as janelas com o modelo treinado e marca as anômalas."""
    t = preparar_features_if(tabela)
    t["score_if"] = modelo.decision_function(t[FEATURES_IF])
    t["anomalia_if"] = modelo.predict(t[FEATURES_IF]) == -1
    return t


# ============================================================================
#  AVALIAÇÃO COMPLETA
# ============================================================================

def avaliar_regioes(casos, modelo_if=None, hoje=DATA_REFERENCIA):
    """Gera os alertas atuais (surto, preventivo e raiva) com a confirmação do Isolation Forest salvo."""
    tabela = calcular_estatisticas(montar_janelas(casos, hoje))
    alertas = gerar_alertas_regionais(tabela, janela=0)
    alertas["caso_unico"] = False
    if modelo_if is None:
        modelo_if = treinar_isolation_forest(tabela)
    t_if = marcar_anomalias(tabela, modelo_if)
    confirmados = t_if[(t_if["janela"] == 0) & t_if["anomalia_if"]][["bairro", "doenca", "especie"]]
    chave = set(map(tuple, confirmados.to_numpy()))
    alertas["confirmado_if"] = [(b, d, e) in chave for b, d, e in zip(alertas["bairro"], alertas["doenca"], alertas["especie"])]
    alertas["motivo"] = [m + (" Confirmado pelo Isolation Forest." if c else "")
                         for m, c in zip(alertas["motivo"], alertas["confirmado_if"])]
    unicos = alertas_caso_unico(casos, hoje)
    if not unicos.empty:
        unicos["confirmado_if"] = False
        alertas = pd.concat([unicos, alertas], ignore_index=True)
    alertas["recomendacao"] = [recomendacao(n, d, e, u) for n, d, e, u in
                               zip(alertas["nivel_risco"], alertas["doenca"], alertas["especie"], alertas["caso_unico"])]
    return alertas.reset_index(drop=True)


def doencas_em_surto_por_regiao(alertas):
    """Doenças em surto (MEDIO ou ALTO) por bairro e espécie, para o Vigia B."""
    ativos = alertas[alertas["nivel_risco"].isin(["MEDIO", "ALTO"])]
    return {k: sorted(set(v)) for k, v in ativos.groupby(["bairro", "especie"])["doenca"]}


# ============================================================================
#  ANIMAIS VULNERÁVEIS DO BAIRRO
# ============================================================================

def animais_vulneraveis(alertas, animais, vacinacoes, vacina_previne):
    """Lista os animais do bairro sem a vacina da doença do alerta."""
    por_animal = {aid: dict(grupo.groupby("nm_vacina")["st_vacinacao"].apply(set))
                  for aid, grupo in vacinacoes.groupby("id_animal")}

    def situacao(estados):
        if not estados or "EFETUADA" not in estados:
            return "nunca tomou"
        return "atrasada" if "ATRASADA" in estados else "em dia"

    linhas = []
    for alerta in alertas.itertuples(index=False):
        cobre = {v: doencas[(alerta.doenca, alerta.especie)] for v, doencas in vacina_previne.items()
                 if (alerta.doenca, alerta.especie) in doencas}
        if not cobre:
            continue
        vizinhos = animais[(animais["bairro"] == alerta.bairro) & (animais["especie"] == alerta.especie)]
        for a in vizinhos.itertuples(index=False):
            vac = por_animal.get(a.id_animal, {})
            estados = {v: situacao(vac.get(v)) for v in cobre}
            if any(estados[v] == "em dia" and cobre[v] == "total" for v in cobre):
                continue                                   # vacinado
            parcial = any(estados[v] == "em dia" for v in cobre)
            texto = "; ".join(f"{v}: {s}" for v, s in estados.items()) + (" (proteção parcial)" if parcial else "")
            linhas.append({"bairro": alerta.bairro, "doenca": alerta.doenca, "especie": alerta.especie,
                           "nivel_alerta": alerta.nivel_risco, "id_animal": a.id_animal, "nm_animal": a.nm_animal,
                           "idade_anos": round(float(a.idade_anos), 1), "situacao_vacinal": texto})
    return pd.DataFrame(linhas, columns=["bairro", "doenca", "especie", "nivel_alerta", "id_animal", "nm_animal",
                                         "idade_anos", "situacao_vacinal"])
