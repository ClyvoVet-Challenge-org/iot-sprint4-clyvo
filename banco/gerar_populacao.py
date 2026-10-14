"""
Gerador do script de população do banco Oracle (03_clyvo_populacao.sql)
Uso: python gerar_populacao.py

Os DADOS DE PACIENTES são simulados. Já as REFERÊNCIAS (raças, pesos, doenças, vacinas, 
fórmulas de consumo, rações) são lidas das planilhas da pasta referencias, as mesmas que 
geram o script 02.
Assim, os animais simulados seguem exatamente as referências usadas pela IA.
"""

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

HOJE = date(2026, 10, 4)                 # data de referência da demonstração
INICIO_HISTORICO = date(2024, 10, 1)     # 2 anos de histórico clínico
DIAS_LEITURA = 60
N_ANIMAIS = 500
FRACAO_SO_VIGIA_C = 0.25                 # filhotes e SRD
PASTA = Path(__file__).resolve().parent

# Procura a pasta referencias/ (ao lado desta pasta ou acima dela)
PASTA_REF = next((p for base in (PASTA, PASTA.parent, PASTA.parent.parent)
                  for p in (base / "referencias", base / "dados" / "referencias")
                  if (p / "ref_peso.csv").exists()), PASTA)
ARQUIVO_SAIDA = PASTA / "03_clyvo_populacao.sql"
SENHA_HASH = "$2b$10$.0Ww5rDfJKhz2Ge5ab8VTOkgwuMGfRGtpQda5HtRVIo4dtyTSP3X2"   # hash de exemplo (projeto Java)


def ler(nome):
    with open(PASTA_REF / nome, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ============================================================================
#  REFERÊNCIAS (lidas das planilhas)
# ============================================================================
REF_PESO = {(r["especie"], r["raca"], {"Ambos": "A"}.get(r["sexo"], r["sexo"])):
            (float(r["peso_min_kg"]), float(r["peso_max_kg"])) for r in ler("ref_peso.csv")}
RACAS = sorted({(e, r) for e, r, _ in REF_PESO})
CATALOGO = ler("catalogo_doencas.csv")
DOENCA_ID = {(d["doenca"], d["especie"]): i for i, d in enumerate(CATALOGO, start=1)}   # mesma ordem do script 02
CRONICAS = {(d["doenca"], d["especie"]): d for d in ler("ref_doencas.csv")}
CRONICAS_NOMES = {d for d, _ in CRONICAS}
PREDISP = {}
for p in ler("ref_predisposicao.csv"):
    PREDISP.setdefault((p["especie"], p["raca"]), []).append(p)
CONSUMO = {(c["especie"], c["castrado"]): c for c in ler("ref_consumo.csv")}
RACOES = ler("ref_racoes.csv")
KCAL_MEDIA = {e: sum(float(r["kcal_kg"]) for r in RACOES if r["especie"] == e) /
              len([r for r in RACOES if r["especie"] == e]) for e in ("Canina", "Felina")}
VACINAS = {}
for v in ler("ref_vacinas.csv"):
    VACINAS.setdefault(v["vacina"], set()).add(v["especie"])

# Frequência das raças na simulação (apenas para sortear; não é referência da IA)
FREQ_RACA = {"Shih Tzu": 10, "Spitz Alemão": 7, "Labrador Retriever": 6, "Golden Retriever": 6, "Pug": 5,
             "Lhasa Apso": 5, "Schnauzer Miniatura": 4, "Border Collie": 3, "Pastor Alemão": 3, "Rottweiler": 3,
             "Husky Siberiano": 3, "Poodle Standard": 2, "Cocker Spaniel Inglês": 2,
             "Cavalier King Charles Spaniel": 2, "West Highland White Terrier": 2, "Staffordshire Bull Terrier": 2,
             "Shar-Pei": 2, "Border Terrier": 1,
             "Persa": 6, "Maine Coon": 3, "Ragdoll": 3, "Azul Russo": 2, "Exótico": 2, "Norueguês da Floresta": 2}
assert set(FREQ_RACA) == {r for _, r in RACAS}, "lista de raças diferente da ref_peso.csv"


def faixa_peso(especie, raca, sexo):
    return REF_PESO.get((especie, raca, sexo)) or REF_PESO[(especie, raca, "A")]


def idade_adulta(especie, raca):
    """12 meses; 18 meses para cães de porte grande (peso máximo > 25 kg) — seção 12.1."""
    if especie == "Canina" and faixa_peso(especie, raca, "A")[1] > 25:
        return 1.5
    return 1.0


# ============================================================================
#  CONTEÚDO SIMULADO DE CADASTRO (textos e medicamentos; não usados pela IA)
# ============================================================================
HISTORICO_DOENCA = {
    "Cinomose": "Febre, secrecao ocular e nasal e tosse. Teste rapido positivo para cinomose. Isolamento e suporte.",
    "Parvovirose": "Vomito e diarreia com sangue, apatia. Teste positivo para parvovirose. Internacao e fluidoterapia.",
    "Tosse dos canis (gripe canina)": "Tosse seca persistente apos creche para caes. Quadro compativel com tosse dos canis.",
    "Leptospirose": "Febre, ictericia e prostracao apos contato com agua de enchente. Suspeita de leptospirose.",
    "Erliquiose (doença do carrapato)": "Apatia, febre e presenca de carrapatos. Plaquetopenia no hemograma. Erliquiose.",
    "Panleucopenia felina": "Vomito, diarreia e leucopenia no hemograma. Panleucopenia felina.",
    "Rinotraqueite felina": "Espirros, secrecao nasal e ocular. Complexo respiratorio felino (rinotraqueite).",
    "Esporotricose": "Lesoes ulceradas na face e membros, gato com acesso a rua. Citologia compativel com esporotricose.",
    "Raiva": "Suspeita de raiva: mudanca de comportamento e salivacao. Animal isolado, vigilancia notificada.",
    "Hepatite infecciosa canina": "Febre, dor abdominal e opacidade de cornea. Suspeita de hepatite infecciosa canina.",
    "Calicivirose felina": "Ulceras na lingua e secrecao nasal. Quadro compativel com calicivirose.",
    "Artrose": "Claudicacao e dificuldade para levantar. Radiografia compativel com artrose.",
    "Obesidade": "Escore corporal elevado. Orientado ajuste de dieta e aumento de atividade fisica.",
    "Hipotireoidismo": "Letargia e ganho de peso. T4 total baixo. Hipotireoidismo.",
    "Doença degenerativa da válvula mitral": "Sopro sistolico em foco mitral. Ecocardiograma compativel com doenca valvar.",
    "Síndrome de Cushing": "Sede e apetite aumentados, abdomen abaulado. Teste de estimulacao com ACTH compativel com Cushing.",
    "Hipoadrenocorticismo (Addison)": "Apatia, falta de apetite e vomitos. Sodio baixo e potassio alto. Addison.",
    "Diabetes mellitus": "Sede e apetite aumentados com perda de peso. Glicemia elevada. Diabetes mellitus.",
    "Doença renal policística": "Ultrassom com cistos renais. Doenca renal policistica.",
    "Cardiomiopatia hipertrófica": "Sopro cardiaco. Ecocardiograma com espessamento do ventriculo esquerdo.",
}
HISTORICO_ROTINA = ["Avaliacao de rotina, animal saudavel.", "Check-up anual e atualizacao vacinal. Sem alteracoes.",
                    "Retorno: boa evolucao clinica, alta.", "Consulta preventiva. Exame fisico normal.",
                    "Avaliacao de rotina. Orientacoes sobre alimentacao e atividade."]
# medicamento, qt, dias, dose, un_dose, freq, un_freq, forma (dados simulados de cadastro)
MEDICAMENTOS = {
    "Cinomose": [("Amoxicilina", 20, 10, 250, "mg", 12, "horas", "SOLIDA")],
    "Parvovirose": [("Metronidazol", 14, 7, 15, "mg/kg", 12, "horas", "SOLIDA"),
                    ("Ondansetrona", 1, 5, 0.5, "mg/kg", 12, "horas", "LIQUIDA")],
    "Tosse dos canis (gripe canina)": [("Doxiciclina", 10, 10, 10, "mg/kg", 24, "horas", "SOLIDA")],
    "Leptospirose": [("Doxiciclina", 28, 14, 10, "mg/kg", 24, "horas", "SOLIDA")],
    "Erliquiose (doença do carrapato)": [("Doxiciclina", 28, 28, 10, "mg/kg", 24, "horas", "SOLIDA")],
    "Panleucopenia felina": [("Ondansetrona", 1, 5, 0.5, "mg/kg", 12, "horas", "LIQUIDA")],
    "Rinotraqueite felina": [("Doxiciclina", 10, 10, 5, "mg/kg", 12, "horas", "SOLIDA")],
    "Esporotricose": [("Itraconazol", 60, 60, 100, "mg", 24, "horas", "SOLIDA")],
    "Artrose": [("Meloxicam", 1, 10, 0.1, "mg/kg", 24, "horas", "LIQUIDA")],
    "Hipotireoidismo": [("Levotiroxina", 60, 60, 20, "mcg/kg", 12, "horas", "SOLIDA")],
    "Síndrome de Cushing": [("Trilostano", 30, 30, 2, "mg/kg", 24, "horas", "SOLIDA")],
    "Diabetes mellitus": [("Insulina", 1, 30, 1, "UI/kg", 12, "horas", "LIQUIDA")],
    "Doença degenerativa da válvula mitral": [("Pimobendan", 60, 30, 0.25, "mg/kg", 12, "horas", "SOLIDA")],
}

BAIRROS = [("Lapa", "05040", ["Rua Guaicurus", "Rua Catao", "Rua Doze de Outubro"]),
           ("Pinheiros", "05422", ["Rua Cardeal Arcoverde", "Rua dos Pinheiros", "Rua Teodoro Sampaio"]),
           ("Mooca", "03104", ["Rua da Mooca", "Rua Javari", "Rua Taquari"]),
           ("Tatuape", "03307", ["Rua Tuiuti", "Rua Itapura", "Rua Serra de Botucatu"]),
           ("Santana", "02012", ["Rua Voluntarios da Patria", "Rua Alfredo Pujol", "Rua Dr. Cesar"]),
           ("Vila Mariana", "04110", ["Rua Domingos de Morais", "Rua Joaquim Tavora", "Rua Vergueiro"]),
           ("Butanta", "05501", ["Av. Vital Brasil", "Rua Alvarenga", "Rua Camargo"]),
           ("Ipiranga", "04208", ["Rua Bom Pastor", "Rua Silva Bueno", "Rua Agostinho Gomes"]),
           ("Perdizes", "05015", ["Rua Cardoso de Almeida", "Rua Monte Alegre", "Rua Cayowaa"]),
           ("Penha", "03602", ["Rua Padre Benedito de Camargo", "Rua Gabriela Mistral", "Av. Gabriela Mistral"])]
BAIRRO_INFO = {b[0]: b for b in BAIRROS}
PRIMEIROS_NOMES = ["Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela", "Joao",
                   "Karina", "Lucas", "Mariana", "Nicolas", "Olivia", "Pedro", "Rafaela", "Samuel", "Tatiana",
                   "Vinicius", "Beatriz", "Caio", "Fernanda", "Gustavo", "Helena", "Igor", "Juliana", "Leonardo",
                   "Larissa", "Marcelo", "Natalia", "Otavio", "Paula", "Renato", "Sabrina", "Thiago", "Vanessa",
                   "Yasmin", "Andre", "Camila"]
SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa", "Rodrigues", "Almeida",
              "Nascimento", "Ferreira", "Araujo", "Carvalho", "Gomes", "Martins", "Rocha", "Ribeiro", "Barbosa",
              "Teixeira", "Mendes", "Nunes", "Moreira", "Cardoso", "Tanaka", "Yamamoto", "Sato", "Fujita",
              "Duarte", "Prado", "Castro"]
NOMES_ANIMAIS = ["Bob", "Nina", "Max", "Lola", "Bela", "Toby", "Simba", "Nala", "Pandora", "Amora", "Pacoca",
                 "Zeus", "Apolo", "Kiara", "Mia", "Frida", "Chico", "Bento", "Teodoro", "Ozzy", "Maya", "Lily",
                 "Belinha", "Theo", "Billy", "Duke", "Jade", "Cookie", "Brownie", "Feijao", "Malu", "Gaia", "Fiona",
                 "Tobias", "Paris", "Sushi", "Biscoito", "Pingo", "Lupita", "Bolinha", "Docinho", "Faisca", "Nego",
                 "Princesa", "Pretinha", "Mel", "Tom", "Lua", "Sol", "Kira"]


# ============================================================================
#  FUNÇÕES AUXILIARES
# ============================================================================
def sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    if isinstance(v, bool):
        raise TypeError("booleano não suportado")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.2f}"
    return "'" + str(v).replace("'", "''") + "'"


def gerar_cpf(usados):
    while True:
        n = [random.randint(0, 9) for _ in range(9)]
        if len(set(n)) == 1:
            continue
        for _ in range(2):
            soma = sum(d * (len(n) + 1 - i) for i, d in enumerate(n))
            dv = (soma * 10) % 11
            n.append(0 if dv == 10 else dv)
        s = "".join(map(str, n))
        cpf = f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"
        if cpf not in usados:
            usados.add(cpf)
            return cpf


def gerar_cnpj(usados):
    while True:
        n = [random.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
        for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
            resto = sum(d * p for d, p in zip(n, pesos)) % 11
            n.append(0 if resto < 2 else 11 - resto)
        s = "".join(map(str, n))
        cnpj = f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
        if cnpj not in usados:
            usados.add(cnpj)
            return cnpj


def unico(gerador, usados):
    while True:
        v = gerador()
        if v not in usados:
            usados.add(v)
            return v


def idade_anos(nasc, ref=HOJE):
    return (ref - nasc).days / 365.25


def nascimento(idade):
    return HOJE - timedelta(days=int(idade * 365.25))


def em_pico(mes, ini, fim):
    if not ini:
        return False
    ini, fim = int(ini), int(fim)
    return ini <= mes <= fim if ini <= fim else (mes >= ini or mes <= fim)


# ============================================================================
#  CADASTROS BÁSICOS
# ============================================================================
responsaveis, end_responsaveis, vets, clinicas, end_clinicas, clinica_vets = [], [], [], [], [], []
animais, end_animais, vacinacoes, consultas, prescricoes, medicamentos, consulta_doencas, leituras = \
    [], [], [], [], [], [], [], []
cpfs, cnpjs, emails, crmvs, rgs, chips = set(), set(), set(), set(), set(), set()


def novo_endereco(bairro):
    _, cep, ruas = BAIRRO_INFO[bairro]
    return {"pais": "Brasil", "estado": "SP", "cidade": "Sao Paulo", "bairro": bairro,
            "logradouro": random.choice(ruas), "nr_rua": str(random.randint(10, 2500)),
            "complemento": random.choice([None, None, "Casa", f"Apto {random.randint(11, 184)}", "Fundos"]),
            "cep": f"{cep}-{random.randint(0, 999):03d}"}


for i, (nome, bairro) in enumerate([("Clinica Amigo Fiel", "Lapa"), ("PetSaude 24 Horas", "Pinheiros"),
                                    ("Hospital Vet Mooca", "Mooca"), ("Clinica Patas e Cia", "Santana"),
                                    ("VetCare Vila Mariana", "Vila Mariana"), ("Clinica Bicho Feliz", "Penha"),
                                    ("Clinica Gato e Cia", "Tatuape")], start=1):
    email = f"contato{i}@{nome.lower().replace(' ', '')[:18]}.com.br"
    emails.add(email)
    clinicas.append({"id": i, "cnpj": gerar_cnpj(cnpjs), "nome": nome, "email": email, "bairro": bairro})
    end_clinicas.append({"id": i, **novo_endereco(bairro), "id_clinica": i})

for i in range(1, 18):
    fem = random.random() < 0.6
    vets.append({"id": i, "nome": f"{'Dra.' if fem else 'Dr.'} {random.choice(PRIMEIROS_NOMES)} {random.choice(SOBRENOMES)}",
                 "cpf": gerar_cpf(cpfs), "crmv": unico(lambda: f"SP{random.randint(10000, 99999)}", crmvs),
                 "email": unico(lambda: f"vet{random.randint(100, 999)}@clyvo.com.br", emails)})

vets_por_clinica = {c["id"]: [] for c in clinicas}
for v in vets:
    for id_clinica in random.sample([c["id"] for c in clinicas], k=random.choice([1, 1, 2])):
        clinica_vets.append({"id": len(clinica_vets) + 1, "id_clinica": id_clinica, "id_vet": v["id"]})
        vets_por_clinica[id_clinica].append(len(clinica_vets))
for c in clinicas:
    if not vets_por_clinica[c["id"]]:
        clinica_vets.append({"id": len(clinica_vets) + 1, "id_clinica": c["id"], "id_vet": random.choice(vets)["id"]})
        vets_por_clinica[c["id"]].append(len(clinica_vets))
CLINICA_POR_BAIRRO = {c["bairro"]: c["id"] for c in clinicas}


def novo_responsavel(nome=None, bairro=None):
    rid = len(responsaveis) + 1
    nome = nome or f"{random.choice(PRIMEIROS_NOMES)} {random.choice(SOBRENOMES)}"
    base = nome.lower().replace(" ", ".")
    responsaveis.append({"id": rid, "nome": nome, "cpf": gerar_cpf(cpfs),
                         "tel": f"(11) 9{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                         "email": unico(lambda: f"{base}{random.randint(1, 999)}@email.com", emails)})
    end_responsaveis.append({"id": rid, **novo_endereco(bairro or random.choice(BAIRROS)[0]), "id_responsavel": rid})
    return rid


# ============================================================================
#  ANIMAIS
# ============================================================================
def escolher_racao(especie, raca, castrado, informada=True):
    if not informada:
        return None
    opcoes = [r for r in RACOES if r["especie"] == especie]
    if especie == "Felina":
        opcoes = [r for r in opcoes if r["para_castrados"] == castrado] or opcoes
    elif raca != "Shih Tzu":
        opcoes = [r for r in opcoes if "Shih Tzu" not in r["produto"]]
    return int(float(random.choice(opcoes)["kcal_kg"]))


def novo_animal(nome, especie, raca, nasc, peso, sexo, castrado, kcal, id_resp, bairro,
                perfil="normal", perfil_consulta="regular", cenario=None, grupo="B"):
    aid = len(animais) + 1
    animais.append({"id": aid, "nome": nome, "nasc": nasc, "peso": round(peso, 2), "especie": especie, "raca": raca,
                    "sexo": sexo, "castrado": castrado, "kcal": kcal,
                    "rg": unico(lambda: f"RG-{random.randint(100000, 999999)}", rgs) if random.random() < 0.4 else None,
                    "chip": unico(lambda: f"MC-{random.randint(10**9, 10**10 - 1)}", chips) if random.random() < 0.6 else None,
                    "id_resp": id_resp, "bairro": bairro, "perfil": perfil, "perfil_consulta": perfil_consulta,
                    "cenario": cenario, "grupo": grupo})
    end_animais.append({"id": aid, **novo_endereco(bairro), "id_animal": aid})
    return animais[-1]


# --- Perfis escondidos: doenças crônicas coerentes com as predisposições -----
SINAL_ALVO = {"comida": {1: 1.40, -1: 0.55}, "agua": {1: 1.70, -1: 0.70}, "movimento": {1: 1.30, -1: 0.55}}


def sortear_perfil(especie, raca, idade):
    """Sorteia no máximo uma condição crônica escondida.
    Chance base de 2,5% por doença, multiplicada pela razão de risco da raça
    (predisposição) ou reduzida (proteção), só depois da idade de risco."""
    candidatos = []
    relacoes = {p["doenca"]: p for p in PREDISP.get((especie, raca), [])}
    for (doenca, esp), d in CRONICAS.items():
        if esp != especie or idade < float(d["idade_risco_anos"]):
            continue
        chance = 0.025
        rel = relacoes.get(doenca)
        if rel and rel["tipo"] == "predisposicao":
            chance *= min(float(rel["razao_risco"]) if rel["razao_risco"] else 3.0, 4.0)
        elif rel and rel["tipo"] == "protecao":
            chance *= 0.4
        candidatos.append((doenca, chance))
    for doenca, chance in candidatos:
        if random.random() < chance:
            return doenca
    if random.random() < 0.04:
        return "queda_apetite"      # alteração aguda inespecífica
    return "normal"


def peso_inicial(especie, raca, sexo, perfil):
    pmin, pmax = faixa_peso(especie, raca, sexo)
    if perfil == "Obesidade":
        return pmax * random.uniform(1.12, 1.30)
    if perfil in ("Hipoadrenocorticismo (Addison)", "Diabetes mellitus"):
        return random.uniform(pmin * 0.92, (pmin + pmax) / 2)
    if random.random() < 0.04:
        return pmin * random.uniform(0.80, 0.93)                 # alguns abaixo do peso
    return random.uniform(pmin, pmax)


# --- Personagens da demonstração (nomes fixos, citados no README e no vídeo) -
P = {}
r = novo_responsavel("Joao Pereira", "Pinheiros")
P["rex"] = novo_animal("Rex", "Canina", "Labrador Retriever", date(2020, 5, 14), 40.0, "M", "S", 3713, r,
                       "Pinheiros", "Obesidade", "regular", "rex")
r = novo_responsavel("Fernanda Tanaka", "Vila Mariana")
P["mel"] = novo_animal("Mel", "Canina", "Golden Retriever", date(2018, 6, 20), 29.5, "F", "S", 3588, r,
                       "Vila Mariana", "mel", "regular", "mel")
r = novo_responsavel("Helena Castro", "Perdizes")
P["mimi"] = novo_animal("Mimi", "Felina", "Persa", date(2017, 2, 10), 3.4, "F", "S", 3740, r,
                        "Perdizes", "mimi", "regular", "mimi")
r = novo_responsavel("Ricardo Nunes", "Mooca")
P["fred"] = novo_animal("Fred", "Canina", "Schnauzer Miniatura", date(2016, 3, 5), 8.2, "M", "S", None, r,
                        "Mooca", "fred", "regular", "fred")
r = novo_responsavel("Lucas Moreira", "Lapa")
P["thor"] = novo_animal("Thor", "Canina", "Border Collie", date(2022, 4, 11), 19.0, "M", "N", 3713, r,
                        "Lapa", "thor", "regular", "thor")
r = novo_responsavel("Beatriz Rocha", "Santana")
P["pipoca"] = novo_animal("Pipoca", "Canina", "Pug", date(2021, 8, 30), 7.3, "F", "S", 3713, r,
                          "Santana", "normal", "irregular", "pipoca")
r = novo_responsavel("Gustavo Sato", "Ipiranga")
P["luna"] = novo_animal("Luna", "Felina", "Ragdoll", date(2023, 3, 15), 4.4, "F", "S", 3800, r,
                        "Ipiranga", "normal", "regular", "luna")
r = novo_responsavel("Marina Duarte", "Butanta")
P["frajola"] = novo_animal("Frajola", "Felina", "SRD", date(2022, 1, 10), 4.6, "M", "N", 3912, r,
                           "Butanta", "normal", "regular", "raiva", grupo="C")


def animal_aleatorio(id_resp, bairro_resp, so_vigia_c, especie=None, bairro=None):
    bairro = bairro or (bairro_resp if random.random() > 0.08 else random.choice(BAIRROS)[0])
    sexo = random.choice("MF")
    nome = random.choice(NOMES_ANIMAIS)
    if so_vigia_c:
        especie = especie or ("Canina" if random.random() < 0.6 else "Felina")
        if random.random() < 0.5:                                  # filhote (2 a 11 meses)
            raca = "SRD" if random.random() < 0.5 else random.choice([r for e, r in RACAS if e == especie])
            idade = random.uniform(0.17, 0.92)
            if raca == "SRD":
                adulto = random.uniform(8, 25) if especie == "Canina" else random.uniform(3.5, 5)
            else:
                adulto = sum(faixa_peso(especie, raca, sexo)) / 2
            peso = adulto * min(1.0, 0.25 + 0.75 * idade)
            castrado = "N"
        else:                                                      # SRD adulto
            raca, idade = "SRD", random.uniform(1, 14)
            peso = random.uniform(6, 30) if especie == "Canina" else random.uniform(3, 5.5)
            castrado = "S" if random.random() < 0.6 else "N"
        kcal = escolher_racao(especie, raca, castrado, informada=random.random() > 0.15)
        return novo_animal(nome, especie, raca, nascimento(idade), peso, sexo, castrado, kcal, id_resp, bairro,
                           "normal", "regular" if random.random() < 0.6 else "irregular", grupo="C")
    especie, raca = random.choices(RACAS, weights=[FREQ_RACA[r] for _, r in RACAS])[0]
    idade = random.uniform(idade_adulta(especie, raca), 14 if especie == "Canina" else 16)
    perfil = sortear_perfil(especie, raca, idade)
    castrado = "S" if random.random() < 0.6 else "N"
    kcal = escolher_racao(especie, raca, castrado, informada=random.random() > 0.10)
    return novo_animal(nome, especie, raca, nascimento(idade), peso_inicial(especie, raca, sexo, perfil), sexo,
                       castrado, kcal, id_resp, bairro, perfil, "regular" if random.random() < 0.65 else "irregular")


# Animais garantidos para os cenários do Vigia C (casos plantados)
for _ in range(10):        # cães jovens/SRD na Lapa (surto de cinomose)
    animal_aleatorio(novo_responsavel(bairro="Lapa"), "Lapa", True, "Canina", "Lapa")
for _ in range(8):         # gatos SRD no Tatuapé (esporotricose)
    animal_aleatorio(novo_responsavel(bairro="Tatuape"), "Tatuape", True, "Felina", "Tatuape")

n_so_c = int(N_ANIMAIS * FRACAO_SO_VIGIA_C)
while len(animais) < N_ANIMAIS:
    id_resp = novo_responsavel()
    bairro_resp = end_responsaveis[-1]["bairro"]
    for _ in range(random.choices([1, 2, 3], weights=[65, 27, 8])[0]):
        if len(animais) >= N_ANIMAIS:
            break
        faltam_c = n_so_c - sum(a["grupo"] == "C" for a in animais)
        so_c = faltam_c > 0 and random.random() < faltam_c / max(1, N_ANIMAIS - len(animais))
        animal_aleatorio(id_resp, bairro_resp, so_c)


# ============================================================================
#  VACINAÇÃO (reforço de 12 meses — ref_vacinas.csv)
# ============================================================================
def vacinas_do_animal(a):
    nomes = [v for v, esp in VACINAS.items() if a["especie"] in esp]
    if "Gripe canina" in nomes and random.random() > 0.55:
        nomes.remove("Gripe canina")                             # vacina opcional
    return nomes


def add_vac(aid, nome, prevista, efetuada, status):
    vacinacoes.append({"id": len(vacinacoes) + 1, "nome": nome, "prevista": prevista, "efetuada": efetuada,
                       "status": status, "id_animal": aid})


for a in animais:
    idade = idade_anos(a["nasc"])
    if idade < 1:                                                # filhotes: série inicial
        if random.random() < 0.4:                                # tutor ainda não vacinou
            a["sem_vacina"] = True
            add_vac(a["id"], [v for v in VACINAS if v.startswith("Polivalente") and a["especie"] in VACINAS[v]][0],
                    a["nasc"] + timedelta(days=45), None, "ATRASADA" if a["nasc"] + timedelta(days=45) < HOJE else "PENDENTE")
            continue
        poli = [v for v in VACINAS if v.startswith("Polivalente") and a["especie"] in VACINAS[v]][0]
        dia = a["nasc"] + timedelta(days=45)
        while dia < HOJE and dia < a["nasc"] + timedelta(days=45 + 42 + 1):
            add_vac(a["id"], poli, dia, dia + timedelta(days=random.randint(0, 3)), "EFETUADA")
            dia += timedelta(days=21)
        add_vac(a["id"], poli, dia if dia > HOJE else a["nasc"] + timedelta(days=365), None, "PENDENTE")
        if idade > 0.34:
            dia_r = a["nasc"] + timedelta(days=100)
            add_vac(a["id"], "Antirrábica", dia_r, dia_r + timedelta(days=random.randint(0, 5)), "EFETUADA")
        continue
    for vacina in vacinas_do_animal(a):
        if a["cenario"] == "raiva" and vacina == "Antirrábica":
            continue                                             # Frajola nunca tomou antirrábica
        if a["cenario"] == "thor" and vacina.startswith("Polivalente"):
            ultima = date(2025, 6, 10)                           # vencida desde 10/06/2026
        elif a["cenario"] in ("rex", "mel", "mimi", "fred", "pipoca", "luna"):
            ultima = HOJE - timedelta(days=random.randint(60, 250))
        else:
            ultima = HOJE - timedelta(days=random.randint(30, 480))
        anterior = ultima - timedelta(days=365)
        if anterior > INICIO_HISTORICO:
            add_vac(a["id"], vacina, anterior, anterior + timedelta(days=random.randint(0, 6)), "EFETUADA")
        add_vac(a["id"], vacina, ultima, ultima + timedelta(days=random.randint(0, 6)), "EFETUADA")
        proxima = ultima + timedelta(days=365)
        if random.random() < 0.03 and a["cenario"] is None:
            add_vac(a["id"], vacina, proxima, None, "CANCELADA")
        else:
            add_vac(a["id"], vacina, proxima, None, "ATRASADA" if proxima < HOJE else "PENDENTE")


def polivalente_em_atraso(a):
    return any(v["id_animal"] == a["id"] and v["nome"].startswith("Polivalente") and v["status"] == "ATRASADA"
               for v in vacinacoes)


# ============================================================================
#  CONSULTAS E DIAGNÓSTICOS
# ============================================================================
INICIO_JANELA = HOJE - timedelta(days=14)        # janela atual do Vigia C
BASE_INFECCIOSAS = {"Cinomose": 3, "Parvovirose": 4, "Tosse dos canis (gripe canina)": 6, "Leptospirose": 2,
                    "Erliquiose (doença do carrapato)": 5, "Hepatite infecciosa canina": 0.5,
                    "Panleucopenia felina": 3, "Rinotraqueite felina": 7, "Esporotricose": 4,
                    "Calicivirose felina": 3}


def sortear_doenca(a, dia):
    candidatas, pesos = [], []
    jovem_sem_vacina = a.get("sem_vacina") or idade_anos(a["nasc"], dia) < 1
    for d in CATALOGO:
        nome = d["doenca"]
        if d["especie"] != a["especie"] or nome not in BASE_INFECCIOSAS:
            continue
        peso = BASE_INFECCIOSAS[nome]
        if nome in ("Parvovirose", "Panleucopenia felina", "Cinomose") and jovem_sem_vacina:
            peso *= 3
        if em_pico(dia.month, d["mes_inicio_pico"], d["mes_fim_pico"]):
            peso *= 2.5
        if dia >= INICIO_JANELA and nome == "Leptospirose":
            peso = 0                                             # só o caso plantado na Penha
        if nome == "Cinomose" and a["bairro"] == "Lapa" and dia >= HOJE - timedelta(days=120):
            peso = 0                                             # Lapa sem cinomose antes do surto
        if nome == "Esporotricose" and a["bairro"] == "Tatuape" and dia >= HOJE - timedelta(days=60):
            peso = 0                                             # base baixa antes do surto
        if peso > 0:
            candidatas.append(nome)
            pesos.append(peso)
    return random.choices(candidatas, weights=pesos)[0] if candidatas else None


def clinica_do_animal(a):
    if "clinica" not in a:
        a["clinica"] = CLINICA_POR_BAIRRO.get(a["bairro"]) if random.random() < 0.7 else None
        a["clinica"] = a["clinica"] or random.choice(clinicas)["id"]
    return a["clinica"]


def add_consulta(a, dia, status, doenca=None, historico=None, prescrever=None):
    cid = len(consultas) + 1
    historico = historico or (HISTORICO_DOENCA[doenca] if doenca else random.choice(HISTORICO_ROTINA))
    consultas.append({"id": cid, "historico": historico[:200], "status": status, "data": dia,
                      "id_vet_cli": random.choice(vets_por_clinica[clinica_do_animal(a)]), "id_animal": a["id"]})
    if doenca:
        consulta_doencas.append({"id": len(consulta_doencas) + 1, "id_consulta": cid,
                                 "id_doenca": DOENCA_ID[(doenca, a["especie"])]})
        if (prescrever if prescrever is not None else random.random() < 0.6) and MEDICAMENTOS.get(doenca):
            pid = len(prescricoes) + 1
            meds = MEDICAMENTOS[doenca]
            prescricoes.append({"id": pid, "emissao": dia, "expiracao": dia + timedelta(days=max(m[2] for m in meds) + 30),
                                "obs": "Retornar se nao houver melhora.", "id_consulta": cid})
            for m in meds:
                medicamentos.append({"id": len(medicamentos) + 1, "nome": m[0], "qt": m[1], "dias": m[2],
                                     "dose": float(m[3]), "un_dose": m[4], "freq": m[5], "un_freq": m[6],
                                     "forma": m[7], "id_prescricao": pid})
    return cid


for a in animais:
    inicio = max(INICIO_HISTORICO, a["nasc"] + timedelta(days=45))
    if a["cenario"] == "pipoca":                                 # mais de 1 ano sem consulta (rotina)
        ultima = HOJE - timedelta(days=random.randint(430, 470))
        add_consulta(a, ultima - timedelta(days=200), "PASSADA")
        add_consulta(a, ultima, "PASSADA")
        continue
    if a["cenario"] == "raiva":
        add_consulta(a, HOJE - timedelta(days=300), "PASSADA")
        continue
    if a["perfil_consulta"] == "irregular" and a["cenario"] is None:
        ultima = HOJE - timedelta(days=random.randint(380, 700))
        datas = [ultima] if random.random() < 0.5 else [ultima - timedelta(days=random.randint(90, 240)), ultima]
    else:
        datas, dia = [], inicio + timedelta(days=random.randint(0, 120))
        while dia < HOJE - timedelta(days=5):
            datas.append(dia)
            dia += timedelta(days=random.randint(110, 230))
    for dia in datas:
        if dia < inicio:
            continue
        if random.random() < 0.05 and a["cenario"] is None:
            add_consulta(a, dia, "CANCELADA", historico="Consulta cancelada pelo tutor.")
            continue
        doenca = sortear_doenca(a, dia) if (random.random() < 0.30 and a["cenario"] is None) else None
        add_consulta(a, dia, "PASSADA", doenca)
    # parte dos animais com condição crônica escondida já tem o diagnóstico registrado
    if a["perfil"] in CRONICAS_NOMES:
        if a["cenario"] is None and random.random() < 0.25:
            add_consulta(a, HOJE - timedelta(days=random.randint(60, 300)), "PASSADA", a["perfil"])
    if random.random() < 0.10 and a["cenario"] is None:
        add_consulta(a, HOJE + timedelta(days=random.randint(3, 30)), "FUTURA",
                     historico="Consulta agendada: retorno e avaliacao geral.")

# Consultas de contexto dos personagens (sem o diagnóstico que a IA vai sugerir)
add_consulta(P["mel"], HOJE - timedelta(days=150), "PASSADA",
             historico="Check-up anual. Exame fisico normal. Orientado manter atividade fisica regular.")
add_consulta(P["mimi"], HOJE - timedelta(days=120), "PASSADA",
             historico="Check-up geriatrico. Creatinina no limite superior. Reavaliar em 6 meses.")
add_consulta(P["fred"], HOJE - timedelta(days=200), "PASSADA",
             historico="Check-up anual. Tutor relata que o animal anda pedindo mais comida.")

# --- Cenários do Vigia C (últimos 14 dias) -----------------------------------
def dia_na_janela():
    return HOJE - timedelta(days=random.randint(1, 13))         # sempre dentro dos 14 dias


caes_lapa = [a for a in animais if a["bairro"] == "Lapa" and a["especie"] == "Canina" and a["cenario"] is None]
caes_lapa.sort(key=lambda a: (not (a.get("sem_vacina") or polivalente_em_atraso(a)), a["grupo"] != "C"))
for a in caes_lapa[:8]:
    add_consulta(a, dia_na_janela(), "PASSADA", "Cinomose", prescrever=True)

gatos_tatuape = [a for a in animais if a["bairro"] == "Tatuape" and a["especie"] == "Felina"
                 and a["cenario"] is None and idade_anos(a["nasc"]) >= 1]
gatos_tatuape.sort(key=lambda a: (a["raca"] != "SRD", a["sexo"] != "M"))
for a in gatos_tatuape[:5]:
    add_consulta(a, dia_na_janela(), "PASSADA", "Esporotricose", prescrever=True)

cao_penha = next(a for a in animais if a["bairro"] == "Penha" and a["especie"] == "Canina" and a["cenario"] is None)
add_consulta(cao_penha, HOJE - timedelta(days=4), "PASSADA", "Leptospirose", prescrever=True)

add_consulta(P["frajola"], HOJE - timedelta(days=2), "PASSADA", "Raiva", prescrever=False)


# ============================================================================
#  LEITURAS DO SENSOR (adultos das 24 raças; consumo esperado pelas fórmulas MSD)
# ============================================================================
def consumo_esperado(a):
    pmin, pmax = faixa_peso(a["especie"], a["raca"], a["sexo"])
    p = min(max(a["peso"], pmin), pmax)                          # peso limitado à faixa ideal
    c = CONSUMO[(a["especie"], a["castrado"])]
    kcal_dia = float(c["coef_rer"]) * p ** float(c["expoente"]) * float(c["fator_manutencao"])
    kcal_kg = a["kcal"] or KCAL_MEDIA[a["especie"]]
    return kcal_dia / kcal_kg * 1000, float(c["coef_agua_ml"]) * p ** float(c["expoente"])


def rampa(d, janela, alvo):
    dias_ate_hoje = DIAS_LEITURA - 1 - d
    return 1 + (alvo - 1) * max(0.0, (janela - dias_ate_hoje) / janela)


def fatores(a, d):
    perfil = a["perfil"]
    if perfil == "Obesidade":
        return 1.45 if a["cenario"] == "rex" else 1.38, 1.0, 0.72
    if perfil == "mel":
        return 1.0, 1.0, rampa(d, 14, 0.50)
    if perfil == "mimi":
        return rampa(d, 14, 0.95), rampa(d, 14, 1.75), 1.0
    if perfil == "fred":
        return rampa(d, 14, 1.40), rampa(d, 14, 1.65), 1.0
    if perfil == "thor":
        return rampa(d, 5, 0.75), rampa(d, 5, 0.92), rampa(d, 5, 0.85)
    if perfil == "queda_apetite":
        return rampa(d, 10, 0.55), rampa(d, 10, 0.85), rampa(d, 10, 0.85)
    if perfil in CRONICAS_NOMES:
        info = CRONICAS[(perfil, a["especie"])]
        tardio = info["momento_sinal"] == "tardio"
        f = []
        for chave in ("comida", "agua", "movimento"):
            sinal = {"aumenta": 1, "diminui": -1}.get(info[chave] or "", 0)
            alvo = SINAL_ALVO[chave].get(sinal, 1.0)
            if tardio:
                alvo = 1 + (alvo - 1) * 0.5
            f.append(rampa(d, 21, alvo))
        return tuple(f)
    return 1.0, 1.0, 1.0


primeiro_dia = HOJE - timedelta(days=DIAS_LEITURA)
for a in animais:
    if a["grupo"] != "B":
        continue
    comida_esp, agua_esp = consumo_esperado(a)
    a["comida_esperada"], a["agua_esperada"] = comida_esp, agua_esp
    idade = idade_anos(a["nasc"])
    mov_base = (55 if a["especie"] == "Canina" else 35) * (0.8 if idade >= 8 else 1.0)
    if a["cenario"]:
        indiv = (1.0, 1.0, 1.0)
    else:
        indiv = (random.gauss(1, 0.08), random.gauss(1, 0.10), random.gauss(1, 0.10))
    for d in range(DIAS_LEITURA):
        dia = primeiro_dia + timedelta(days=d)
        fc, fa, fm = fatores(a, d)
        leituras.append({"id": len(leituras) + 1, "id_animal": a["id"],
                         "dt": datetime(dia.year, dia.month, dia.day, 20, 0, 0),
                         "comida": round(max(0.0, comida_esp * indiv[0] * fc * random.gauss(1, 0.06)), 2),
                         "agua": round(max(0.0, agua_esp * indiv[1] * fa * random.gauss(1, 0.08)), 2),
                         "mov": round(min(100.0, max(0.0, mov_base * indiv[2] * fm * random.gauss(1, 0.08))), 2),
                         "disp": f"clyvo-esp32-{a['id']:04d}"})


# ============================================================================
#  ESCRITA DO SQL
# ============================================================================
linhas = []
w = linhas.append


def lote(tabela, colunas, registros, por_lote):
    for i in range(0, len(registros), por_lote):
        w("INSERT ALL")
        for reg in registros[i:i + por_lote]:
            w(f"  INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join(sql(v) for v in reg)})")
        w("SELECT 1 FROM DUAL;")
    w("COMMIT;")
    w("")


w("-- ============================================================================")
w("--  Script 03: População do banco (gerado por gerar_populacao.py)")
w(f"--  Dados de pacientes SIMULADOS. Data de referência: {HOJE.isoformat()} | semente: {SEED}")
w("--  Ordem de execução: 01 -> 02 -> 03")
w("-- ============================================================================")
w("SET DEFINE OFF;")
w("SET FEEDBACK OFF;")
w("")
w("-- Clínicas, endereços, veterinários e vínculos")
lote("T_CLYVO_CLINICA", ["id_clinica", "cnpj_clinica", "nm_clinica", "email", "senha", "st_contrato"],
     [(c["id"], c["cnpj"], c["nome"], c["email"], SENHA_HASH, "ATIVO") for c in clinicas], 50)
lote("T_CLYVO_ENDERECO_CLINICA", ["id", "pais", "estado", "cidade", "bairro", "logradouro", "nr_rua", "complemento", "cep", "id_clinica"],
     [(e["id"], e["pais"], e["estado"], e["cidade"], e["bairro"], e["logradouro"], e["nr_rua"], e["complemento"], e["cep"], e["id_clinica"]) for e in end_clinicas], 50)
lote("T_CLYVO_VET", ["id_vet", "nm_vet", "cpf_vet", "crmv_vet", "email", "senha"],
     [(v["id"], v["nome"], v["cpf"], v["crmv"], v["email"], SENHA_HASH) for v in vets], 50)
lote("T_CLYVO_CLINICA_VET", ["id_clinica_vet", "id_clinica", "id_veterinario"],
     [(cv["id"], cv["id_clinica"], cv["id_vet"]) for cv in clinica_vets], 100)
w("-- Responsáveis e endereços")
lote("T_CLYVO_RESPONSAVEL", ["id_responsavel", "nm_responsavel", "cpf_responsavel", "nr_telefone_responsavel", "ds_email"],
     [(r["id"], r["nome"], r["cpf"], r["tel"], r["email"]) for r in responsaveis], 100)
lote("T_CLYVO_ENDERECO_RESPONSAVEL", ["id", "pais", "estado", "cidade", "bairro", "logradouro", "nr_rua", "complemento", "cep", "id_responsavel"],
     [(e["id"], e["pais"], e["estado"], e["cidade"], e["bairro"], e["logradouro"], e["nr_rua"], e["complemento"], e["cep"], e["id_responsavel"]) for e in end_responsaveis], 80)
w("-- Animais e endereços")
lote("T_CLYVO_ANIMAL", ["id_animal", "nm_animal", "dt_nascimento_animal", "peso_animal", "especie_animal", "raca_animal",
                        "sexo_animal", "castrado", "kcal_kg_racao", "rg_animal", "nr_microchip_animal", "id_responsavel"],
     [(a["id"], a["nome"], a["nasc"], float(a["peso"]), a["especie"], a["raca"], a["sexo"], a["castrado"], a["kcal"],
       a["rg"], a["chip"], a["id_resp"]) for a in animais], 80)
lote("T_CLYVO_ENDERECO_ANIMAL", ["id", "pais", "estado", "cidade", "bairro", "logradouro", "nr_rua", "complemento", "cep", "id_animal"],
     [(e["id"], e["pais"], e["estado"], e["cidade"], e["bairro"], e["logradouro"], e["nr_rua"], e["complemento"], e["cep"], e["id_animal"]) for e in end_animais], 80)
w("-- Vacinação")
lote("T_CLYVO_VACINACAO", ["id_vacinacao", "nm_vacina", "dt_vacinacao_prevista", "dt_vacinacao_efetuada", "st_vacinacao", "id_animal"],
     [(v["id"], v["nome"], v["prevista"], v["efetuada"], v["status"], v["id_animal"]) for v in vacinacoes], 120)
w("-- Consultas, diagnósticos, prescrições e medicamentos")
lote("T_CLYVO_CONSULTA", ["id_consulta", "historico_consulta", "st_consulta", "dt_consulta", "id_vet_cli", "id_animal"],
     [(c["id"], c["historico"], c["status"], c["data"], c["id_vet_cli"], c["id_animal"]) for c in consultas], 120)
lote("T_CLYVO_CONSULTA_DOENCA", ["id_consulta_doenca", "id_consulta", "id_doenca"],
     [(cd["id"], cd["id_consulta"], cd["id_doenca"]) for cd in consulta_doencas], 200)
lote("T_CLYVO_PRESCRICAO", ["id_prescricao", "dt_emissao", "dt_expiracao", "observacoes_gerais", "id_consulta"],
     [(p["id"], p["emissao"], p["expiracao"], p["obs"], p["id_consulta"]) for p in prescricoes], 150)
lote("T_CLYVO_MEDICAMENTO", ["id", "nm_medicamento", "qt_medicamento", "qt_dias", "vl_dose", "un_dose", "qt_frequencia",
                             "un_frequencia", "forma_farmaceutica", "id_prescricao"],
     [(m["id"], m["nome"], m["qt"], m["dias"], m["dose"], m["un_dose"], m["freq"], m["un_freq"], m["forma"], m["id_prescricao"]) for m in medicamentos], 80)
w("-- Leituras simuladas do ESP32 (1 por dia, 20h, últimos 60 dias) — adultos das 24 raças")
lote("T_CLYVO_LEITURA_SENSOR", ["id_leitura", "id_animal", "dt_leitura", "consumo_comida_g", "consumo_agua_ml", "nivel_movimento", "id_dispositivo"],
     [(l["id"], l["id_animal"], l["dt"], l["comida"], l["agua"], l["mov"], l["disp"]) for l in leituras], 120)
w("-- Contadores IDENTITY depois dos IDs inseridos explicitamente")
for tabela, coluna in [("T_CLYVO_CLINICA", "id_clinica"), ("T_CLYVO_ENDERECO_CLINICA", "id"), ("T_CLYVO_VET", "id_vet"),
                       ("T_CLYVO_CLINICA_VET", "id_clinica_vet"), ("T_CLYVO_RESPONSAVEL", "id_responsavel"),
                       ("T_CLYVO_ENDERECO_RESPONSAVEL", "id"), ("T_CLYVO_ANIMAL", "id_animal"),
                       ("T_CLYVO_ENDERECO_ANIMAL", "id"), ("T_CLYVO_VACINACAO", "id_vacinacao"),
                       ("T_CLYVO_CONSULTA", "id_consulta"), ("T_CLYVO_CONSULTA_DOENCA", "id_consulta_doenca"),
                       ("T_CLYVO_PRESCRICAO", "id_prescricao"), ("T_CLYVO_MEDICAMENTO", "id"),
                       ("T_CLYVO_LEITURA_SENSOR", "id_leitura")]:
    w(f"ALTER TABLE {tabela} MODIFY ({coluna} GENERATED BY DEFAULT ON NULL AS IDENTITY (START WITH LIMIT VALUE));")
w("")
w("SET FEEDBACK ON;")
w("-- Conferência")
w("SELECT 'Animais' AS tabela, COUNT(*) AS qtd FROM T_CLYVO_ANIMAL")
w("UNION ALL SELECT 'Responsaveis', COUNT(*) FROM T_CLYVO_RESPONSAVEL")
w("UNION ALL SELECT 'Consultas', COUNT(*) FROM T_CLYVO_CONSULTA")
w("UNION ALL SELECT 'Diagnosticos', COUNT(*) FROM T_CLYVO_CONSULTA_DOENCA")
w("UNION ALL SELECT 'Vacinacoes', COUNT(*) FROM T_CLYVO_VACINACAO")
w("UNION ALL SELECT 'Leituras', COUNT(*) FROM T_CLYVO_LEITURA_SENSOR;")
ARQUIVO_SAIDA.write_text("\n".join(linhas) + "\n", encoding="utf-8")

if __name__ == "__main__":
    print(f"Arquivo {ARQUIVO_SAIDA.name} gerado.")
    print(f"  Animais: {len(animais)} (Vigia B: {sum(a['grupo'] == 'B' for a in animais)}, "
          f"só Vigia C: {sum(a['grupo'] == 'C' for a in animais)}) | Responsaveis: {len(responsaveis)}")
    print(f"  Consultas: {len(consultas)} | Diagnosticos: {len(consulta_doencas)} | Vacinacoes: {len(vacinacoes)}"
          f" | Leituras: {len(leituras)}")
