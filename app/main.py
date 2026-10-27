"""Clyvo Vet — aplicação de demonstração da IA (Vigia B e Vigia C)."""

import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
load_dotenv(PASTA / ".env")

import servico_ia  # noqa: E402

servico = servico_ia.ServicoIA()


def avaliar():
    try:
        servico.avaliar()
    except Exception as erro:
        servico.limpar()
        servico.erro = str(erro)


@asynccontextmanager
async def iniciar(app):
    avaliar()
    yield


app = FastAPI(title="Clyvo Vet — API de IA", description="Alertas individuais (Vigia B) e regionais (Vigia C).",
              lifespan=iniciar)
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")
templates = Jinja2Templates(directory=PASTA / "templates")


# Formatação para as telas
def br(valor, casas=1):
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def linha_svg(valores, largura=300, altura=56):
    """Pontos de um gráfico de linha simples (SVG)."""
    if not valores:
        return ""
    menor, maior = min(valores), max(valores)
    faixa = (maior - menor) or 1
    passo = largura / max(len(valores) - 1, 1)
    return " ".join(f"{i * passo:.1f},{altura - 4 - (v - menor) / faixa * (altura - 8):.1f}" for i, v in enumerate(valores))


templates.env.filters["br"] = br
templates.env.globals.update(linha_svg=linha_svg, local=servico_ia.nome_local, pct=servico_ia.pct,
                             data_ref=servico_ia.data_referencia)


def tela(request, nome, aba, **contexto):
    if servico.erro:
        return templates.TemplateResponse(request, "erro.html", {"erro": servico.erro, "aba": aba})
    return templates.TemplateResponse(request, nome, {"aba": aba, "resumo": servico.resumo(), **contexto})


# ============================================================================
#  TELAS
# ============================================================================

@app.get("/", include_in_schema=False)
def inicio(request: Request, msg: str = ""):
    return tela(request, "inicio.html", "inicio", em_risco=servico.em_risco()[:6], regionais=servico.regionais, msg=msg)


@app.get("/pacientes", include_in_schema=False)
def pacientes(request: Request, nivel: str = "risco"):
    todos = sorted(servico.animais.values(), key=lambda a: a["nome"])
    if nivel == "risco":
        lista = servico.em_risco()
    elif nivel in ("ALTO", "MEDIO", "BAIXO"):
        lista = sorted([a for a in todos if a["avaliado"] and a["nivel"] == nivel], key=lambda a: -a["confianca"])
    elif nivel == "rotina":
        lista = [a for a in todos if a["rotina"]]
    elif nivel == "fora":
        lista = [a for a in todos if not a["avaliado"]]
    else:
        lista = todos
    return tela(request, "pacientes.html", "pacientes", lista=lista, nivel=nivel)


@app.get("/animal/{id_animal}", include_in_schema=False)
def animal(request: Request, id_animal: int, msg: str = ""):
    a = servico.animais.get(id_animal)
    if a is None:
        raise HTTPException(404, "Animal não encontrado")
    regionais = [r for r in servico.regionais if r["bairro"] == a["bairro"] and r["especie"] == a["especie"]]
    return tela(request, "animal.html", "pacientes", a=a, regionais=regionais, msg=msg)


@app.post("/animal/{id_animal}/leitura", include_in_schema=False)
def simular_leitura(id_animal: int, comida: float = Form(...), agua: float = Form(...), movimento: float = Form(...),
                    dias: int = Form(3)):
    antes = servico.animais.get(id_animal, {}).get("nivel")
    servico_ia.registrar_leituras(id_animal, comida, agua, movimento, max(1, min(dias, 7)))
    avaliar()
    depois = servico.animais.get(id_animal, {}).get("nivel")
    msg = f"{dias} leitura(s) do sensor registrada(s). Risco antes: {antes} → agora: {depois}."
    return RedirectResponse(f"/animal/{id_animal}?msg={msg}", status_code=303)


@app.get("/regional", include_in_schema=False)
def regional(request: Request, msg: str = ""):
    return tela(request, "regional.html", "regional", regionais=servico.regionais, msg=msg)


@app.get("/regional/{indice}", include_in_schema=False)
def regional_detalhe(request: Request, indice: int):
    if not 0 <= indice < len(servico.regionais):
        raise HTTPException(404, "Alerta não encontrado")
    return tela(request, "regional_detalhe.html", "regional", r=servico.regionais[indice])


# WhatsApp: cada tutor tem a sua conversa; o alerta sanitário vai para todos os tutores do bairro
def _mensagens_do_tutor(telefone):
    animais = sorted([x for x in servico.animais.values() if x["telefone"] == telefone], key=lambda x: x["nome"])
    mensagens = []
    for x in animais:
        if x["avaliado"] and x["nivel"] != "BAIXO":
            mensagens.append({"tipo": "saude", "titulo": f"Alerta de saúde — {x['nome']}",
                              "texto": servico_ia.mensagem_individual(x), "botao": "Agendar consulta"})
        elif x["rotina"]:
            mensagens.append({"tipo": "checkup", "titulo": f"Lembrete de check-up — {x['nome']}",
                              "texto": servico_ia.mensagem_rotina(x), "botao": "Agendar check-up"})
    vistos = set()
    for r in servico.regionais:
        if any(r["bairro"] == x["bairro"] and r["especie"] == x["especie"] for x in animais) \
                and (r["bairro"], r["doenca"]) not in vistos:
            vistos.add((r["bairro"], r["doenca"]))
            mensagens.append({"tipo": "sanitario", "titulo": r["titulo_mensagem"], "texto": r["mensagem"],
                              "botao": "Agendar consulta preventiva"})
    return animais, mensagens


def _regionais_agrupados():
    """Um alerta por bairro e doença (a raiva, por exemplo, vale para cães e gatos)."""
    grupos = {}
    for r in servico.regionais:
        g = grupos.setdefault((r["bairro"], r["doenca"]), {**r, "especies": [], "telefones": set(), "indices": []})
        g["indices"].append(r["indice"])
        g["especies"].append("cães" if r["especie"] == "Canina" else "gatos")
        g["telefones"] |= {x["telefone"] for x in servico.animais.values()
                           if x["bairro"] == r["bairro"] and x["especie"] == r["especie"]}
    return [{**g, "tutores": len(g["telefones"])} for g in grupos.values()]


def _ordem_conversa(x):
    """Ordem da lista: saúde ALTO, saúde MÉDIO e depois check-up."""
    if x["avaliado"] and x["nivel"] != "BAIXO":
        return 0 if x["nivel"] == "ALTO" else 1
    return 2


@app.get("/whatsapp", include_in_schema=False)
def whatsapp(request: Request, tipo: str = "todas", animal: int = 0):
    if animal:
        return RedirectResponse(f"/whatsapp/tutor/{animal}", status_code=303)
    conversas = [{"tipo": "sanitario", "nome": f"Tutores · {servico_ia.nome_local(g['bairro'])}",
                  "detalhe": f"{g['tutores']} tutores de {' e '.join(g['especies'])}", "nivel": g["nivel_risco"],
                  "previa": g["mensagem"].split("\n")[0], "link": f"/whatsapp/regional/{g['indice']}"}
                 for g in _regionais_agrupados()]
    por_tutor = {}
    for x in sorted(servico.animais.values(), key=lambda x: (_ordem_conversa(x), -x.get("confianca", 0))):
        if x["telefone"] in por_tutor or not ((x["avaliado"] and x["nivel"] != "BAIXO") or x["rotina"]):
            continue
        animais, mensagens = _mensagens_do_tutor(x["telefone"])
        principal = mensagens[0]
        por_tutor[x["telefone"]] = {"tipo": principal["tipo"], "nome": x["tutor"],
                                    "detalhe": ", ".join(a["nome"] for a in animais),
                                    "nivel": x["nivel"] if principal["tipo"] == "saude" else None,
                                    "previa": principal["texto"].split("\n")[0], "link": f"/whatsapp/tutor/{x['id_animal']}"}
    conversas += list(por_tutor.values())
    contagem = {t: sum(1 for c in conversas if c["tipo"] == t) for t in ("sanitario", "saude", "checkup")}
    lista = conversas if tipo == "todas" else [c for c in conversas if c["tipo"] == tipo]
    return tela(request, "whatsapp_lista.html", "whatsapp", conversas=lista, tipo=tipo, contagem=contagem,
                total=len(conversas))


@app.get("/whatsapp/tutor/{id_animal}", include_in_schema=False)
def whatsapp_tutor(request: Request, id_animal: int):
    a = servico.animais.get(id_animal)
    if a is None:
        raise HTTPException(404, "Animal não encontrado")
    animais, mensagens = _mensagens_do_tutor(a["telefone"])
    contato = {"nome": a["tutor"], "detalhe": "responsável por " + ", ".join(x["nome"] for x in animais), "icone": "👤"}
    return tela(request, "whatsapp.html", "whatsapp", mensagens=mensagens, contato=contato)


@app.get("/whatsapp/regional/{indice}", include_in_schema=False)
def whatsapp_regional(request: Request, indice: int):
    g = next((g for g in _regionais_agrupados() if indice in g["indices"]), None)
    if g is None:
        raise HTTPException(404, "Alerta não encontrado")
    contato = {"nome": f"Tutores · {servico_ia.nome_local(g['bairro'])}",
               "detalhe": f"lista de transmissão · {g['tutores']} tutores de {' e '.join(g['especies'])}", "icone": "👥"}
    mensagens = [{"tipo": "sanitario", "titulo": g["titulo_mensagem"], "texto": g["mensagem"],
                  "botao": "Agendar consulta preventiva"}]
    return tela(request, "whatsapp.html", "whatsapp", mensagens=mensagens, contato=contato)


@app.get("/diagnostico", include_in_schema=False)
def diagnostico(request: Request, erro: str = ""):
    animais = sorted(servico.animais.values(), key=lambda a: (a["bairro"] or "", a["nome"]))
    doencas = servico_ia.doencas_infecciosas() if not servico.erro else []
    return tela(request, "diagnostico.html", "diagnostico", animais=animais, doencas=doencas, erro=erro,
                hoje=servico_ia.data_referencia())


@app.post("/diagnostico", include_in_schema=False)
def registrar(id_animal: int = Form(...), id_doenca: int = Form(...), data_consulta: date = Form(...)):
    a = servico.animais.get(id_animal)
    doenca = next((d for d in servico_ia.doencas_infecciosas() if int(d["id_doenca"]) == id_doenca), None)
    if a is None or doenca is None:
        return RedirectResponse("/diagnostico?erro=Escolha um animal e uma doença.", status_code=303)
    if doenca["especie_alvo"] != a["especie"]:
        return RedirectResponse(f"/diagnostico?erro={doenca['nm_doenca']} não atinge a espécie de {a['nome']}.",
                                status_code=303)
    servico_ia.registrar_diagnostico(id_animal, id_doenca, data_consulta,
                                     f"[Demonstração] Diagnóstico de {doenca['nm_doenca']} registrado pela aplicação de IA.")
    avaliar()
    msg = (f"Diagnóstico de {doenca['nm_doenca']} registrado para {a['nome']} ({servico_ia.nome_local(a['bairro'])}). "
           f"A IA foi executada de novo com o dado novo.")
    return RedirectResponse(f"/regional?msg={msg}", status_code=303)


@app.post("/diagnostico/limpar", include_in_schema=False)
def limpar_demonstracoes():
    servico_ia.remover_demonstracoes()
    avaliar()
    return RedirectResponse("/regional?msg=Dados de demonstração removidos (diagnósticos e leituras simuladas).",
                            status_code=303)


@app.post("/atualizar", include_in_schema=False)
def atualizar():
    avaliar()
    return RedirectResponse("/?msg=IA executada novamente com os dados do banco.", status_code=303)


# ============================================================================
#  API
# ============================================================================

def _dados_api(a):
    dados = {k: a[k] for k in ("id_animal", "nome", "especie", "raca", "idade", "bairro", "avaliado")}
    dados["checkup_atrasado"] = a["rotina"]
    if a["avaliado"]:
        dados.update({"nivel_risco": a["nivel"], "confianca": round(a["confianca"], 2),
                      "probabilidades": {k: round(v, 2) for k, v in a["probabilidades"].items()},
                      "causa_provavel": a["causa"], "outras_hipoteses": a["outras_hipoteses"],
                      "doencas_da_raca_na_idade_de_risco": a["doencas_raca"], "sinais": a["sinais"]})
    else:
        dados["motivo"] = a["motivo_fora"]
    dados["doencas_em_surto_no_bairro"] = a["doencas_regionais"]
    dados["recomendacao"] = a["recomendacao"]
    return dados


def _verificar():
    if servico.erro:
        raise HTTPException(503, f"IA indisponível: {servico.erro}")


@app.get("/api/resumo", tags=["Resumo"], summary="Números gerais da última execução da IA")
def api_resumo():
    _verificar()
    return {**servico.resumo(), "modelo_vigia_b": servico.nome_modelo_b, "acuracia_teste": servico.acuracia_b,
            "data_referencia": servico_ia.data_referencia(), "executado_em": servico.ultima_avaliacao}


@app.get("/api/animais/em-risco", tags=["Vigia B — alerta individual"], summary="Animais com risco ALTO ou MÉDIO")
def api_em_risco():
    _verificar()
    return [_dados_api(a) for a in servico.em_risco()]


@app.get("/api/animais/{id_animal}/risco", tags=["Vigia B — alerta individual"], summary="Nível de risco de um animal")
def api_risco(id_animal: int):
    _verificar()
    if id_animal not in servico.animais:
        raise HTTPException(404, "Animal não encontrado")
    return _dados_api(servico.animais[id_animal])


@app.get("/api/alertas/regionais", tags=["Vigia C — alerta regional"], summary="Alertas regionais ativos")
def api_regionais():
    _verificar()
    campos = ("bairro", "doenca", "especie", "casos", "media_hist", "z", "nivel_risco", "confirmado_if", "caso_unico",
              "motivo")
    return [{**{k: r[k] for k in campos}, "recomendacao_clinica": r["recomendacao_clinica"],
             "orientacao_tutor": r["recomendacao"], "animais_sem_vacina": len(r["vulneraveis"])} for r in servico.regionais]


class Leitura(BaseModel):
    id_animal: int
    comida_g: float = Field(ge=0)
    agua_ml: float = Field(ge=0)
    movimento: float = Field(ge=0, le=100)


@app.post("/api/leituras", tags=["Vigia B — alerta individual"],
          summary="Recebe uma leitura diária do sensor (formato do ESP32) e devolve o risco atualizado")
def api_leitura(leitura: Leitura):
    if leitura.id_animal not in servico.animais:
        raise HTTPException(404, "Animal não encontrado")
    servico_ia.registrar_leituras(leitura.id_animal, leitura.comida_g, leitura.agua_ml, leitura.movimento, 1)
    avaliar()
    _verificar()
    return _dados_api(servico.animais[leitura.id_animal])


@app.post("/api/avaliar", tags=["Execução"], summary="Executa os dois vigias de novo com os dados do banco")
def api_avaliar():
    avaliar()
    _verificar()
    return api_resumo()
