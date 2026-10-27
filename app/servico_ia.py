"""Liga o banco aos modelos: roda o Vigia C, depois o Vigia B, e monta os alertas."""

import os
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import pandas as pd

PASTA_IA = Path(__file__).resolve().parent.parent / "ia"
sys.path.insert(0, str(PASTA_IA / "vigia_b"))
sys.path.insert(0, str(PASTA_IA / "vigia_c"))

import banco  # noqa: E402
from clyvo_features import (DIAS_ANALISADOS, MIN_DIAS, FEATURES_CATEGORICAS, FEATURES_NUMERICAS,  # noqa: E402
                            avaliado_pelo_vigia_b, carregar_referencias, causa_provavel, extrair_features)
from clyvo_regional import (CONSULTA_CASOS, DATA_REFERENCIA, JANELA_DIAS, animais_vulneraveis,  # noqa: E402
                            avaliar_regioes, doencas_em_surto_por_regiao)

warnings.filterwarnings("ignore", category=UserWarning)

NOMES_BAIRROS = {"Tatuape": "Tatuapé", "Butanta": "Butantã", "Sao Paulo": "São Paulo"}
ORDEM_NIVEL = {"ALTO": 0, "MEDIO": 1, "BAIXO": 2}


def nome_local(texto):
    """Nome do bairro ou cidade com acento, para exibir."""
    return NOMES_BAIRROS.get(texto, texto)


def data_referencia():
    """'Hoje' da demonstração (a data em que os dados simulados terminam)."""
    valor = os.getenv("CLYVO_DATA_REFERENCIA")
    return date.fromisoformat(valor) if valor else DATA_REFERENCIA


def pct(razao):
    """Razão em porcentagem de diferença (1.4 -> 40)."""
    return round(abs(razao - 1) * 100)


def risco_raca(razao):
    """Razão de risco em texto (4.36 -> '4,4×'); sem razão, é mutação genética da raça."""
    return f"{razao:.1f}".replace(".", ",") + "×" if razao else "mutação genética"


def artigo(animal):
    """'a' para fêmea, 'o' para macho."""
    return "a" if animal["sexo"] == "F" else "o"


def recomendacao_clinica(r):
    """Ação recomendada para a clínica, conforme o resultado dos vigias."""
    if r["avaliado"] and r["nivel"] == "ALTO":
        return "Entrar em contato com o responsável e agendar consulta nos próximos dias."
    if r["avaliado"] and r["nivel"] == "MEDIO":
        return "Acompanhar as próximas leituras do sensor e reavaliar; se continuar, agendar consulta."
    if r["sem_vacina_regional"]:
        doencas = " e ".join(sorted({x.split(" (")[0].lower() for x in r["sem_vacina_regional"]}))
        texto = f"Avisar o responsável sobre o alerta de {doencas} no bairro e regularizar a vacina."
        return texto + (" Aproveitar para o check-up de rotina." if r["rotina"] else "")
    if r["rotina"]:
        return "Oferecer check-up de rotina ao responsável (mais de 1 ano sem consulta)."
    if r["doencas_regionais"]:
        return "Informar o responsável sobre o alerta do bairro; a vacinação dele está em dia."
    return "Nenhuma ação no momento: seguir o acompanhamento contínuo."


# ============================================================================
#  TEXTOS PARA A TELA E PARA O WHATSAPP
# ============================================================================

def sinais_em_texto(animal, f, d):
    """Lista os sinais alterados em linguagem simples."""
    sinais = []
    if f["desvio_peso"] > 0:
        sinais.append(f"Peso acima do ideal para a raça ({animal['raca']})")
    elif f["desvio_peso"] < 0:
        sinais.append(f"Peso abaixo do ideal para a raça ({animal['raca']})")
    textos = {("comida", 1): "Comendo mais que o normal", ("comida", -1): "Comendo menos que o normal",
              ("agua", 1): "Bebendo mais água que o normal", ("agua", -1): "Bebendo menos água que o normal",
              ("movimento", 1): "Mais agitado que o normal", ("movimento", -1): "Nível de atividade abaixo do normal"}
    for chave in ("comida", "agua", "movimento"):
        if d["sinais"][chave]:
            sinais.append(textos[(chave, d["sinais"][chave])])
    for doenca in d["doencas_regionais_sem_vacina"]:
        sinais.append(f"Vacina atrasada contra {doenca.lower()}, que está em surto no bairro")
    if f["dias_sem_consulta"] > 365:
        sinais.append("Mais de 1 ano sem consulta veterinária")
    return sinais


def mensagem_individual(r):
    """Mensagem de WhatsApp do alerta individual (Vigia B)."""
    tutor = r["tutor"].split(" ")[0]
    linhas = [f"Olá, {tutor}! Identificamos alguns sinais n{artigo(r)} {r['nome']} nos últimos dias:", ""]
    linhas += [f"- {s}" for s in r["sinais"]] or ["- Mudança no padrão de comida, água ou movimento"]
    causa = r["causa"].split(" (")[0].split(":")[0].lower()
    linhas += ["", f"Juntos, esses sinais indicam atenção para: {causa}."]
    if r["nivel"] == "ALTO":
        linhas.append("Recomendamos agendar uma consulta nos próximos dias.")
    else:
        linhas.append("Vale observar nos próximos dias e, se continuar, agendar uma consulta.")
    return "\n".join(linhas)


def recomendacao_clinica_regional(a, tem_vacina, sem_vacina):
    """Ação recomendada para a clínica diante de um alerta regional."""
    doenca = a["doenca"].lower()
    animais = "cães" if a["especie"] == "Canina" else "gatos"
    if tem_vacina and sem_vacina:
        vacinas = f"Avisar primeiro os tutores dos {sem_vacina} {animais} sem a vacina em dia (lista abaixo) e oferecer a vacinação."
    elif tem_vacina:
        vacinas = f"Os {animais} da clínica no bairro estão com a vacina em dia; manter a orientação aos tutores."
    else:
        vacinas = f"Não há vacina para {doenca}: orientar os tutores do bairro sobre a prevenção."
    if a["caso_unico"]:
        return (f"Caso suspeito de {doenca}: notificar a vigilância em saúde (notificação obrigatória) "
                f"e acompanhar o animal. " + vacinas)
    if a["nivel_risco"] == "BAIXO":
        return f"Época de pico de {doenca}, com caso no bairro. " + vacinas
    return (vacinas + f" Reforçar a atenção aos sintomas de {doenca} nas consultas da região e registrar "
            "todo caso confirmado, para o Vigia C acompanhar a evolução.")


def mensagem_rotina(r):
    """Mensagem de WhatsApp do lembrete de check-up (correlação 9)."""
    tutor = r["tutor"].split(" ")[0]
    if r["dias_sem_consulta"] is None:
        inicio = f"Olá, {tutor}! Ainda não há consultas registradas d{artigo(r)} {r['nome']} aqui na clínica."
    else:
        inicio = f"Olá, {tutor}! Já faz mais de 1 ano desde a última consulta d{artigo(r)} {r['nome']}."
    return "\n".join([inicio, "",
                      "Mesmo sem sinais de problema, o check-up anual ajuda a descobrir doenças cedo, "
                      "quando o tratamento é mais simples.", "", "Que tal agendar um check-up?"])


def mensagem_regional(a):
    """Mensagem de WhatsApp do alerta regional (Vigia C)."""
    bairro, doenca = nome_local(a["bairro"]), a["doenca"].lower()
    if a["caso_unico"]:
        corpo = [f"Foi registrado um caso suspeito de {doenca} na região onde seu pet vive.", "",
                 "Recomendamos:", "✓ Conferir se a vacina antirrábica está em dia",
                 "✓ Evitar contato com animais desconhecidos", "✓ Em caso de mordida, procurar o veterinário ou a vigilância em saúde"]
    elif a["nivel_risco"] == "BAIXO":
        corpo = [f"Estamos na época de maior incidência de {doenca} e houve caso na região onde seu pet vive.", "",
                 "Recomendamos:", "✓ Manter a vacinação em dia", "✓ Evitar água parada e enchentes"]
    else:
        corpo = [f"Nas últimas 2 semanas, identificamos um aumento de casos de {doenca} na região onde seu pet vive.", "",
                 "Recomendamos:", "✓ Verificar a carteira de vacinação", "✓ Evitar contato com animais doentes",
                 "✓ Ficar atento a sintomas e procurar o veterinário"]
    return "\n".join(corpo + ["", "Em caso de dúvida, procure seu veterinário."]), f"Alerta Sanitário — Região {bairro}"


# ============================================================================
#  SERVIÇO
# ============================================================================

class ServicoIA:
    def __init__(self):
        pacote_b = joblib.load(PASTA_IA / "vigia_b" / "modelo_vigia_b.joblib")
        self.modelo_b = pacote_b["modelo"]
        self.nome_modelo_b = pacote_b["nome"]
        self.acuracia_b = pacote_b["acuracia_teste"]
        pacote_c = joblib.load(PASTA_IA / "vigia_c" / "modelo_vigia_c.joblib")
        self.modelo_c = pacote_c["modelo_isolation_forest"]
        self.limpar()

    def limpar(self):
        self.animais, self.regionais, self.vulneraveis = {}, [], pd.DataFrame()
        self.ultima_avaliacao, self.origem_referencias, self.erro = None, None, None

    # ------------------------------------------------------------------
    def avaliar(self):
        """Lê o banco, roda os dois vigias e grava os alertas."""
        hoje = data_referencia()
        inicio = datetime.combine(hoje - timedelta(days=DIAS_ANALISADOS), datetime.min.time())
        with banco.conectar() as con:
            ref = carregar_referencias(con)
            dados = banco.carregar_dados(con, inicio, hoje)
            casos = pd.read_sql(CONSULTA_CASOS, con)
            casos.columns = [c.lower() for c in casos.columns]
            casos["dt_consulta"] = [banco.para_data(x) for x in casos["dt_consulta"]]

            # Vigia C: alertas regionais
            regionais = avaliar_regioes(casos, self.modelo_c, hoje)
            surtos = doencas_em_surto_por_regiao(regionais)

            # Vigia B: alerta individual
            animais = self._vigia_b(dados, ref, surtos, hoje)

            # Animais sem a vacina da doença do alerta regional
            tabela_animais = pd.DataFrame([{"id_animal": a["id_animal"], "nm_animal": a["nome"], "bairro": a["bairro"],
                                            "especie": a["especie"], "idade_anos": a["idade"]} for a in animais.values()])
            vulneraveis = animais_vulneraveis(regionais, tabela_animais, dados["vacinacoes"], ref["vacina_previne"])

            lista_regionais = self._montar_regionais(regionais, vulneraveis, animais, ref["vacina_previne"])

            # Recomendação para a clínica, já sabendo quem está sem a vacina da doença do bairro
            for r in animais.values():
                r["sem_vacina_regional"] = [] if vulneraveis.empty else [
                    f"{v.doenca} ({v.situacao_vacinal})"
                    for v in vulneraveis[vulneraveis["id_animal"] == r["id_animal"]].itertuples()]
                r["recomendacao"] = recomendacao_clinica(r)

            banco.salvar_alertas(con, self._linhas_alerta(animais, lista_regionais, banco.ids_doencas(con)))

        self.regionais = lista_regionais
        self.animais, self.vulneraveis = animais, vulneraveis
        self.origem_referencias, self.ultima_avaliacao, self.erro = ref["origem"], datetime.now(), None

    def _vigia_b(self, dados, ref, surtos, hoje):
        leituras = {k: g for k, g in dados["leituras"].groupby("id_animal")}
        atrasadas = dados["vacinacoes"][dados["vacinacoes"]["st_vacinacao"] == "ATRASADA"] \
            .groupby("id_animal")["nm_vacina"].apply(lambda v: sorted(set(v))).to_dict()
        ultimas = {r.id_animal: banco.para_data(r.ultima) for r in dados["ultimas_consultas"].itertuples()}
        resultado = {}
        for a in dados["animais"].itertuples():
            nascimento = banco.para_data(a.dt_nascimento_animal)
            animal = {"especie": a.especie_animal, "raca": a.raca_animal, "sexo": a.sexo_animal,
                      "idade_anos": (hoje - nascimento).days / 365.25, "peso_kg": float(a.peso_animal),
                      "castrado": a.castrado == "S",
                      "kcal_kg_racao": None if pd.isna(a.kcal_kg_racao) else float(a.kcal_kg_racao)}
            ultima = ultimas.get(a.id_animal)
            base = {"id_animal": int(a.id_animal), "nome": a.nm_animal, "especie": a.especie_animal,
                    "raca": a.raca_animal, "sexo": a.sexo_animal, "idade": round(animal["idade_anos"], 1),
                    "peso": animal["peso_kg"], "castrado": animal["castrado"], "tutor": a.nm_responsavel,
                    "telefone": a.nr_telefone_responsavel, "bairro": a.bairro, "cidade": a.cidade,
                    "dias_sem_consulta": (hoje - ultima).days if ultima else None,
                    "rotina": ultima is None or (hoje - ultima).days > 365,
                    "vacinas_atrasadas": atrasadas.get(a.id_animal, []),
                    "doencas_regionais": surtos.get((a.bairro, a.especie_animal), []), "avaliado": False}
            serie = leituras.get(a.id_animal)
            if not avaliado_pelo_vigia_b(a.especie_animal, a.raca_animal, animal["idade_anos"], ref):
                base["motivo_fora"] = ("Filhote: o Vigia B avalia a partir da idade adulta da raça."
                                       if (a.especie_animal, a.raca_animal) in ref["racas"] else
                                       "Sem raça definida (SRD): não há faixa de peso de referência.")
                resultado[base["id_animal"]] = base
                continue
            if serie is None or len(serie) < MIN_DIAS:
                base["motivo_fora"] = "Sem leituras suficientes do sensor."
                resultado[base["id_animal"]] = base
                continue
            leituras_animal = [{"comida": float(l.consumo_comida_g), "agua": float(l.consumo_agua_ml),
                                "movimento": float(l.nivel_movimento)} for l in serie.itertuples()][-DIAS_ANALISADOS:]
            dias = base["dias_sem_consulta"] if base["dias_sem_consulta"] is not None else 999
            f, d = extrair_features(animal, leituras_animal, base["vacinas_atrasadas"], dias,
                                    base["doencas_regionais"], ref)
            relacoes = {p["doenca"]: p for p in ref["predisp"].get((a.especie_animal, a.raca_animal), [])}
            quatorze = leituras_animal[-14:]
            base.update({"avaliado": True, "causa": causa_provavel(f, d), "features": f, "detalhes": d,
                         "sinais": sinais_em_texto(animal, f, d), "serie": leituras_animal,
                         "doencas_raca": [f"{x} ({risco_raca(relacoes[x]['razao_risco'] if x in relacoes else None)})"
                                          for x in d["doencas_idade_risco"]],
                         "outras_hipoteses": [f"{c['doenca']} ({risco_raca(c['razao_risco'])})"
                                              for c in d["causas_compativeis"] if c["predisposicao"]][1:],
                         "inicio_fim_14": {k: (sum(x[k] for x in quatorze[:3]) / 3, sum(x[k] for x in quatorze[-3:]) / 3)
                                           for k in ("comida", "agua", "movimento")}})
            resultado[base["id_animal"]] = base

        # O modelo avalia todos os animais de uma vez
        avaliados = [r for r in resultado.values() if r["avaliado"]]
        if avaliados:
            entrada = pd.DataFrame([r["features"] for r in avaliados])[FEATURES_CATEGORICAS + FEATURES_NUMERICAS]
            probabilidades = self.modelo_b.predict_proba(entrada)
            for r, linha in zip(avaliados, probabilidades):
                probs = dict(zip(self.modelo_b.classes_, (float(p) for p in linha)))
                r["nivel"] = max(probs, key=probs.get)
                r["confianca"], r["probabilidades"] = probs[r["nivel"]], probs
        return resultado

    def _montar_regionais(self, regionais, vulneraveis, animais, vacina_previne):
        lista = []
        for i, a in enumerate(regionais.to_dict("records")):
            no_bairro = [x for x in animais.values() if x["bairro"] == a["bairro"] and x["especie"] == a["especie"]]
            vul = vulneraveis[(vulneraveis["bairro"] == a["bairro"]) & (vulneraveis["doenca"] == a["doenca"])
                              & (vulneraveis["especie"] == a["especie"])] if not vulneraveis.empty else vulneraveis
            texto, titulo = mensagem_regional(a)
            tem_vacina = any((a["doenca"], a["especie"]) in doencas for doencas in vacina_previne.values())
            lista.append({**a, "indice": i, "media_hist": None if pd.isna(a.get("media_hist")) else float(a["media_hist"]),
                          "z": None if pd.isna(a.get("z")) else float(a["z"]), "pacientes_regiao": len(no_bairro),
                          "vulneraveis": vul.to_dict("records"), "mensagem": texto, "titulo_mensagem": titulo,
                          "recomendacao_clinica": recomendacao_clinica_regional(a, tem_vacina, len(vul))})
        return lista

    def _linhas_alerta(self, animais, regionais, ids):
        linhas = []
        for r in animais.values():
            if r["avaliado"] and r["nivel"] in ("MEDIO", "ALTO"):
                motivo = f"{r['causa']}. Sinais: " + "; ".join(r["sinais"])
                linhas.append({"tp_alerta": "INDIVIDUAL", "vigia_origem": "B", "nivel_risco": r["nivel"],
                               "probabilidade": round(r["confianca"], 4), "ds_motivo": cortar(motivo, 500),
                               "ds_recomendacao": r["recomendacao"],
                               "id_animal": r["id_animal"], "cidade": r["cidade"], "bairro": r["bairro"],
                               "id_doenca": None})
        for r in animais.values():
            if r["rotina"]:
                linhas.append({"tp_alerta": "ROTINA", "vigia_origem": "B", "nivel_risco": "BAIXO", "probabilidade": None,
                               "ds_motivo": "Mais de 1 ano sem consulta veterinária (correlação 9).",
                               "ds_recomendacao": "Agendar check-up de rotina", "id_animal": r["id_animal"],
                               "cidade": r["cidade"], "bairro": r["bairro"], "id_doenca": None})
        for a in regionais:
            linhas.append({"tp_alerta": "REGIONAL", "vigia_origem": "C", "nivel_risco": a["nivel_risco"],
                           "probabilidade": None, "ds_motivo": cortar(a["motivo"], 500),
                           "ds_recomendacao": cortar(a["recomendacao_clinica"], 300), "id_animal": None,
                           "cidade": a["cidade"], "bairro": a["bairro"],
                           "id_doenca": ids.get((a["doenca"], a["especie"]))})
        return linhas

    # ------------------------------------------------------------------
    def em_risco(self):
        """Animais avaliados com risco MÉDIO ou ALTO, do mais urgente para o menos."""
        lista = [a for a in self.animais.values() if a["avaliado"] and a["nivel"] != "BAIXO"]
        return sorted(lista, key=lambda a: (ORDEM_NIVEL[a["nivel"]], -a["confianca"]))

    def resumo(self):
        avaliados = [a for a in self.animais.values() if a["avaliado"]]
        contagem = {n: sum(1 for a in avaliados if a["nivel"] == n) for n in ("ALTO", "MEDIO", "BAIXO")}
        return {"total": len(self.animais), "avaliados": len(avaliados), **contagem,
                "rotina": sum(1 for a in self.animais.values() if a["rotina"]),
                "fora": len(self.animais) - len(avaliados),
                "surtos": sum(1 for a in self.regionais if a["nivel_risco"] in ("MEDIO", "ALTO")),
                "preventivos": sum(1 for a in self.regionais if a["nivel_risco"] == "BAIXO")}


def cortar(texto, limite_bytes):
    """Corta o texto para caber na coluna do Oracle (limite em bytes)."""
    dados = (texto or "").encode("utf-8")
    return texto if len(dados) <= limite_bytes else dados[:limite_bytes - 3].decode("utf-8", "ignore") + "..."


def registrar_diagnostico(id_animal, id_doenca, data_consulta, historico):
    with banco.conectar() as con:
        return banco.registrar_diagnostico(con, id_animal, id_doenca, data_consulta, historico)


def registrar_leituras(id_animal, comida, agua, movimento, dias=3):
    with banco.conectar() as con:
        banco.inserir_leituras(con, id_animal, comida, agua, movimento, dias)


def remover_demonstracoes():
    with banco.conectar() as con:
        return banco.remover_demonstracoes(con)


def doencas_infecciosas():
    with banco.conectar() as con:
        return banco.doencas_infecciosas(con).to_dict("records")


JANELA = JANELA_DIAS
